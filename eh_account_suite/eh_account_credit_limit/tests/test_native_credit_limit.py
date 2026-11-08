# Copyright (C) 2026 ERP Heritage (https://www.erpheritage.com.au/).

from datetime import timedelta
import json
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.eh_account_credit_limit.migration import unify_native_credit_limits
from .test_credit_limit import TestCreditLimit


@tagged('eh_account_credit_limit', 'integration', 'post_install', '-at_install')
class TestNativeCreditLimit(TestCreditLimit):
    """Behavior contracts for the single native amount and upgrade review."""

    def _seed_previous_terms(self, partner=None, amount=None, policy=None):
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE eh_credit_policy SET eh_credit_policy_limit_legacy = %s WHERE id = %s",
            [1000.0, self.policy.id],
        )
        if policy:
            self.env.cr.execute(
                "UPDATE eh_credit_policy SET eh_credit_policy_limit_legacy = %s WHERE id = %s",
                [amount, policy.id],
            )
        elif partner:
            self.env.cr.execute(
                "UPDATE res_partner SET eh_credit_limit_legacy = %s WHERE id = %s",
                [json.dumps({str(self.company.id): amount}), partner.id],
            )
        self.env.invalidate_all()

    def test_native_and_eh_edits_are_the_same_limit(self):
        partner = self.partner_a
        partner.credit_limit = 600.0
        self.assertEqual(partner.eh_credit_limit, 600.0)
        self.assertEqual(partner.eh_effective_credit_limit, 600.0)
        partner.eh_credit_limit = 450.0
        self.assertEqual(partner.credit_limit, 450.0)
        self._customer_invoice(partner, 400.0)
        with self.assertRaisesRegex(UserError, 'Credit limit exceeded'):
            self._customer_invoice(partner, 100.0)
        with self.assertRaisesRegex(ValidationError, 'must agree'):
            partner.write({'credit_limit': 700.0, 'eh_credit_limit': 800.0})

    def test_company_default_is_shared_with_every_policy(self):
        other_policy = self.Policy.create({
            'name': 'Different enforcement, same amount authority',
            'company_id': self.company.id, 'enforcement_mode': 'warn',
        })
        self.company.account_credit_limit = 900.0
        self.assertEqual(self.policy.default_credit_limit, 900.0)
        self.assertEqual(other_policy.default_credit_limit, 900.0)
        self.assertEqual(self.partner_a.credit_limit, 900.0)
        self.policy.default_credit_limit = 750.0
        self.assertEqual(self.company.account_credit_limit, 750.0)
        self.assertEqual(other_policy.default_credit_limit, 750.0)
        self.assertEqual(self.partner_a.eh_effective_credit_limit, 750.0)

    def test_native_zero_and_restore_company_default(self):
        self.partner_a.credit_limit = 0.0
        self.assertEqual(self.partner_a.eh_credit_limit, 0.0)
        invoice = self._customer_invoice(self.partner_a, 1500.0)
        self.assertEqual(invoice.state, 'posted')
        self.partner_a.use_partner_credit_limit = False
        self.assertEqual(self.partner_a.credit_limit, 1000.0)
        with self.assertRaises(UserError):
            self._customer_invoice(self.partner_a, 100.0)

    def test_explicit_alias_zero_on_create_matches_native_zero(self):
        for values, context in (
            ({'eh_credit_limit': 0.0}, {}),
            ({'credit_limit': 0.0}, {}),
            ({}, {'default_eh_credit_limit': 0.0}),
        ):
            partner = self.env['res.partner'].with_context(**context).create({
                'name': 'Explicit zero customer limit', **values,
            })
            self.assertEqual(partner.credit_limit, 0.0)
            self.assertEqual(partner.eh_credit_limit, 0.0)
            invoice = self._customer_invoice(partner, 1500.0)
            self.assertEqual(invoice.state, 'posted')
            with self.assertRaises(AccessError):
                self.env['res.partner'].with_user(self.plain_user).with_context(
                    **context,
                ).create({'name': 'Unprivileged zero customer limit', **values})

    def test_native_configuration_cannot_bypass_manager_or_company_guards(self):
        for value in (0.0, 90000.0):
            with self.assertRaises(AccessError):
                self.partner_a.with_user(self.plain_user).write({'credit_limit': value})
            with self.assertRaises(AccessError):
                self.env['res.partner'].with_user(self.plain_user).create({
                    'name': 'Unprivileged native credit terms', 'credit_limit': value,
                })
        with self.assertRaises(AccessError):
            self.env['res.partner'].with_user(self.plain_user).with_context(
                default_credit_limit=0.0,
            ).create({'name': 'Unprivileged context credit terms'})
        with self.assertRaises(AccessError):
            self.partner_a.with_user(self.plain_user).write({'use_partner_credit_limit': False})
        other = self.env['res.company'].create({'name': 'Native credit other company'})
        a = self.partner_a.with_company(self.company)
        b = self.partner_a.with_company(other)
        a.credit_limit = 111.0
        b.eh_credit_limit = 222.0
        self.assertEqual(a.eh_credit_limit, 111.0)
        self.assertEqual(b.credit_limit, 222.0)
        with self.assertRaises(AccessError):
            b.with_user(self.restricted_manager).write({'credit_limit': 333.0})

    def test_manager_can_edit_company_default_through_policy(self):
        self.policy.with_user(self.restricted_manager).default_credit_limit = 625.0
        self.assertEqual(self.company.account_credit_limit, 625.0)

    def test_changed_native_limit_requires_fresh_override(self):
        invoice = self._customer_invoice(self.partner_a, 1400.0, post=False)
        invoice.eh_credit_override_reason = 'Reviewed at the original limit'
        self.partner_a.credit_limit = 800.0
        with self.assertRaisesRegex(UserError, 'changed after'):
            invoice.action_post()
        invoice.eh_credit_override_reason = 'Reviewed again at 800'
        invoice.action_post()
        self.assertEqual(invoice.eh_credit_override_log_id.limit_at_override, 800.0)

    def test_expired_override_requires_fresh_review(self):
        invoice = self._customer_invoice(self.partner_a, 1400.0, post=False)
        self.policy.override_validity_hours = 1.0
        before = fields.Datetime.now() - timedelta(hours=2)
        with patch.object(fields.Datetime, 'now', return_value=before):
            invoice.eh_credit_override_reason = 'Earlier review'
        with self.assertRaisesRegex(UserError, 'expired'):
            invoice.action_post()
        invoice.eh_credit_override_reason = 'Current review'
        invoice.action_post()
        self.assertEqual(invoice.state, 'posted')

    def test_revoked_reason_author_cannot_approve_later_posting(self):
        group = self.env['res.groups'].create({'name': 'Dedicated credit approvers'})
        self.env.user.group_ids |= group
        self.restricted_manager.group_ids |= group
        self.policy.override_group_id = group
        invoice = self._customer_invoice(self.partner_a, 1400.0, post=False)
        invoice.with_user(self.restricted_manager).eh_credit_override_reason = 'Reviewed before revocation'
        self.restricted_manager.group_ids -= group
        with self.assertRaisesRegex(UserError, 'authorised credit-override user'):
            invoice.action_post()
        self.assertFalse(invoice.eh_credit_override_log_id)

    def test_upgrade_adopts_unambiguous_eh_customer_terms(self):
        self._seed_previous_terms(self.partner_a, 450.0)
        unify_native_credit_limits(self.env)
        self.assertEqual(self.partner_a.credit_limit, 450.0)
        self.assertEqual(self.partner_a.eh_credit_limit, 450.0)
        self.assertEqual(self.partner_a.eh_credit_limit_legacy[str(self.company.id)], 450.0)
        self.assertFalse(self.env['eh.credit.limit.review'].search([('partner_id', '=', self.partner_a.id)]))
        with self.assertRaises(UserError):
            self._customer_invoice(self.partner_a, 500.0)
        unify_native_credit_limits(self.env)
        self.assertEqual(self.partner_a.credit_limit, 450.0)

    def test_upgrade_conflict_preserves_values_and_blocks_until_review(self):
        self.partner_a.credit_limit = 1500.0
        self._seed_previous_terms(self.partner_a, 450.0)
        unify_native_credit_limits(self.env)
        self.assertEqual(self.partner_a.credit_limit, 1500.0)
        review = self.env['eh.credit.limit.review'].search([('partner_id', '=', self.partner_a.id)])
        self.assertEqual(len(review), 1)
        self.assertEqual(review.native_limit, 1500.0)
        self.assertEqual(review.previous_eh_limit, 450.0)
        with self.assertRaisesRegex(ValidationError, 'pending credit-limit conflicts'):
            self.partner_a.parent_id = self.partner_b
        with self.assertRaisesRegex(ValidationError, 'manager review'):
            self._customer_invoice(self.partner_a, 100.0)
        with self.assertRaises(AccessError):
            review.with_user(self.plain_user).action_use_previous_eh()
        # The review action preserves contact ACLs as well as its own manager role.
        with self.assertRaises(AccessError):
            review.with_user(self.restricted_manager).action_use_previous_eh()
        self.restricted_manager.group_ids |= self.env.ref('base.group_partner_manager')
        review.with_user(self.restricted_manager).action_use_previous_eh()
        self.assertEqual(self.partner_a.credit_limit, 450.0)
        self.assertEqual(review.resolved_by_id, self.restricted_manager)
        self.assertEqual(review.native_limit, 1500.0)
        with self.assertRaises(AccessError):
            review.write({'previous_eh_limit': 9000.0})
        with self.assertRaises(ValidationError):
            review.action_keep_native()
        self._customer_invoice(self.partner_a, 400.0)
        with self.assertRaises(UserError):
            self._customer_invoice(self.partner_a, 100.0)

    def test_upgrade_alternate_policy_terms_become_customer_limit(self):
        special = self.Policy.create({'name': 'Legacy special terms', 'company_id': self.company.id})
        self.partner_a.eh_credit_policy_id = special
        self._seed_previous_terms(amount=350.0, policy=special)
        unify_native_credit_limits(self.env)
        self.assertEqual(self.partner_a.credit_limit, 350.0)
        self.assertEqual(self.partner_b.credit_limit, 1000.0)
        self.assertEqual(special.default_credit_limit, 1000.0)
        self.assertEqual(special.eh_credit_policy_limit_legacy, 350.0)

    def test_upgrade_company_default_conflict_and_keep_native(self):
        self._seed_previous_terms()
        self.company.account_credit_limit = 800.0
        unify_native_credit_limits(self.env)
        review = self.env['eh.credit.limit.review'].search([
            ('company_id', '=', self.company.id), ('partner_id', '=', False),
        ])
        self.assertEqual(len(review), 1)
        self.assertEqual(self.company.account_credit_limit, 800.0)
        with self.assertRaisesRegex(ValidationError, 'manager review'):
            self._customer_invoice(self.partner_a, 100.0)
        review.with_user(self.restricted_manager).action_keep_native()
        self._customer_invoice(self.partner_a, 700.0)
        with self.assertRaises(UserError):
            self._customer_invoice(self.partner_a, 200.0)

    def test_upgrade_demoted_customer_terms_require_explicit_review(self):
        child = self.env['res.partner'].create({'name': 'Legacy subsidiary', 'parent_id': self.partner_a.id})
        self._seed_previous_terms(child, 50000.0)
        unify_native_credit_limits(self.env)
        self.assertEqual(self.partner_a.credit_limit, 1000.0)
        review = self.env['eh.credit.limit.review'].search([('partner_id', '=', self.partner_a.id)])
        self.assertEqual(len(review), 1)
        self.assertEqual(review.previous_eh_limit, 50000.0)

    def test_upgrade_company_default_can_adopt_previous_terms(self):
        self._seed_previous_terms()
        self.company.account_credit_limit = 800.0
        unify_native_credit_limits(self.env)
        review = self.env['eh.credit.limit.review'].search([
            ('company_id', '=', self.company.id), ('partner_id', '=', False),
        ])
        review.with_user(self.restricted_manager).action_use_previous_eh()
        self.assertEqual(self.company.account_credit_limit, 1000.0)
        self.assertEqual(review.resolved_limit, 1000.0)
        self.assertEqual(self.partner_a.credit_limit, 1000.0)

    def test_review_actions_cannot_cross_disabled_company(self):
        other = self.env['res.company'].create({'name': 'Credit review isolated company'})
        review = self.env['eh.credit.limit.review']._create_upgrade_review(
            other, self.env['res.partner'], 1000.0, 500.0, 'Isolated test',
        )
        with self.assertRaises(AccessError):
            review.with_user(self.restricted_manager).action_use_previous_eh()
        self.assertEqual(review.state, 'pending')

    def test_native_company_limit_rejects_negative_and_unprivileged_changes(self):
        with self.assertRaises(ValidationError):
            self.company.account_credit_limit = -1.0
        with self.assertRaises(AccessError):
            self.company.with_user(self.plain_user).account_credit_limit = 9000.0
