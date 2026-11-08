# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Mandate state machine tests.

Covers FRST -> RCUR transition on first consume, OOFF immediate
completion, the 36-month dormancy expiry both at consume time and
via the cron, validation guards, and atomic counter increment.
"""

from datetime import date, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch

from dateutil.relativedelta import relativedelta

from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('eh_account_sepa_dd', 'integration', 'post_install', '-at_install')
class TestMandateStateMachine(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Mandate = cls.env['eh.sepa.mandate']
        cls.Creditor = cls.env['eh.sepa.creditor']

        cls.bank_journal = cls.env['account.journal'].search(
            [('type', '=', 'bank'),
             ('company_id', '=', cls.env.company.id)],
            limit=1,
        )
        if not cls.bank_journal:
            cls.bank_journal = cls.env['account.journal'].create({
                'name': 'Test Bank',
                'code': 'TBK',
                'type': 'bank',
                'company_id': cls.env.company.id,
            })

        # Other tests in the same database may have already created a
        # creditor for this journal (the unique constraint is on
        # journal_id alone). Reuse if present.
        existing = cls.Creditor.search(
            [('journal_id', '=', cls.bank_journal.id)], limit=1,
        )
        if existing:
            cls.creditor = existing
        else:
            cls.creditor = cls.Creditor.create({
                'name': 'Demo creditor',
                'journal_id': cls.bank_journal.id,
                'creditor_identifier': 'DE98ZZZ09999999999',
                'creditor_name': 'Demo Co',
                'iban': 'DE89370400440532013000',
            })
        cls.partner = cls.env['res.partner'].create({
            'name': 'Demo customer',
        })

    def _make_mandate(self, **overrides):
        vals = {
            'mandate_id': 'MNDT-TEST-001',
            'creditor_id': self.creditor.id,
            'partner_id': self.partner.id,
            'debtor_iban': 'FR1420041010050500013M02606',
            'signature_date': date(2026, 1, 15),
            'state': 'active',
            'local_instrument': 'CORE',
        }
        vals.update(overrides)
        return self.Mandate.create(vals)

    def _consume(self, mandate, collection_date, mark_final=False):
        return mandate.sudo().with_context(
            eh_sepa_dd_collection_engine=True,
        ).consume_for_collection(collection_date, mark_final=mark_final)

    # ---- next_sequence_type ----

    def test_active_first_use_yields_frst(self):
        m = self._make_mandate()
        self.assertEqual(m.next_sequence_type, 'FRST')

    def test_one_off_yields_ooff(self):
        m = self._make_mandate(is_one_off=True)
        self.assertEqual(m.next_sequence_type, 'OOFF')

    def test_draft_has_no_next_sequence(self):
        m = self._make_mandate(state='draft')
        self.assertFalse(m.next_sequence_type)

    # ---- consume_for_collection ----

    def test_first_consume_returns_frst_and_advances(self):
        m = self._make_mandate()
        seq = self._consume(m, date(2026, 5, 1))
        self.assertEqual(seq, 'FRST')
        m.invalidate_recordset()
        self.assertEqual(m.collection_count, 1)
        self.assertEqual(m.last_collection_date, date(2026, 5, 1))
        self.assertEqual(m.next_sequence_type, 'RCUR')

    def test_second_consume_returns_rcur(self):
        m = self._make_mandate()
        self._consume(m, date(2026, 5, 1))
        seq = self._consume(m, date(2026, 6, 1))
        self.assertEqual(seq, 'RCUR')
        m.invalidate_recordset()
        self.assertEqual(m.collection_count, 2)

    def test_one_off_consume_returns_ooff_and_completes(self):
        m = self._make_mandate(is_one_off=True)
        seq = self._consume(m, date(2026, 5, 1))
        self.assertEqual(seq, 'OOFF')
        m.invalidate_recordset()
        self.assertEqual(m.state, 'completed')

    def test_mark_final_returns_fnal_and_completes(self):
        m = self._make_mandate()
        self._consume(m, date(2026, 5, 1))  # FRST
        seq = self._consume(m, date(2026, 6, 1), mark_final=True)
        self.assertEqual(seq, 'FNAL')
        m.invalidate_recordset()
        self.assertEqual(m.state, 'completed')

    def test_consume_on_draft_raises(self):
        m = self._make_mandate(state='draft')
        with self.assertRaises(UserError):
            self._consume(m, date(2026, 5, 1))

    def test_consume_on_revoked_raises(self):
        m = self._make_mandate()
        m.action_revoke()
        with self.assertRaises(UserError):
            self._consume(m, date(2026, 5, 1))

    # ---- 36-month expiry ----

    def test_consume_on_dormant_mandate_expires_and_raises(self):
        m = self._make_mandate()
        self._consume(m, date(2023, 1, 1))  # FRST in the past
        # Keep the exception inside this test transaction so the uncommitted
        # fixture's documented same-transaction fallback remains observable.
        # Persisted production mandates use the independent committed cursor
        # covered by the focused regression below.
        raised_msg = ''
        try:
            self._consume(m, date(2027, 6, 1))
        except UserError as exc:
            raised_msg = str(exc)
        self.assertIn('dormant', raised_msg.lower())
        m.invalidate_recordset(['state'])
        self.assertEqual(m.state, 'expired')

    def test_durable_expiry_uses_and_commits_independent_cursor(self):
        m = self._make_mandate()

        class FakeCursor:
            def __init__(self):
                self.committed = False
                self.query = ''
                self.params = ()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, query, params):
                self.query = query
                self.params = params

            def fetchone(self):
                return (m.id,)

            def commit(self):
                self.committed = True

        durable = FakeCursor()
        with patch.object(
                type(self.env.registry), 'cursor', return_value=durable):
            updated = m._eh_expire_dormant_durably(date(2027, 6, 1))
        self.assertTrue(updated)
        self.assertTrue(durable.committed)
        self.assertIn("state = 'expired'", durable.query)
        self.assertEqual(durable.params[2], m.id)

    def test_consume_just_before_expiry_succeeds(self):
        m = self._make_mandate()
        first = date(2024, 1, 1)
        self._consume(m, first)
        # 35 months later: still inside the window.
        almost_cutoff = first + relativedelta(months=35)
        seq = self._consume(m, almost_cutoff)
        self.assertEqual(seq, 'RCUR')

    def test_cron_expires_dormant(self):
        m = self._make_mandate()
        # Backdate last collection to far past.
        self._consume(m, date(2020, 1, 1))
        self.Mandate._cron_expire_dormant()
        m.invalidate_recordset()
        self.assertEqual(m.state, 'expired')

    # ---- validation ----

    def test_invalid_iban_rejected(self):
        with self.assertRaises(ValidationError):
            self._make_mandate(debtor_iban='DE99370400440532013000')

    def test_too_long_mandate_id_rejected(self):
        with self.assertRaises(ValidationError):
            self._make_mandate(mandate_id='X' * 36)

    def test_unique_mandate_id_per_company(self):
        self._make_mandate()
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self._make_mandate()

    # ---- transitions ----

    def test_activate_from_draft(self):
        m = self._make_mandate(state='draft')
        m.action_activate()
        self.assertEqual(m.state, 'active')

    def test_activate_from_active_raises(self):
        m = self._make_mandate()
        with self.assertRaises(UserError):
            m.action_activate()

    def test_revoke_clears_active(self):
        m = self._make_mandate()
        m.action_revoke()
        self.assertEqual(m.state, 'revoked')

    def test_used_mandate_cannot_reset_and_erase_collection_history(self):
        m = self._make_mandate()
        self._consume(m, date(2026, 5, 1))
        m.action_revoke()
        with self.assertRaises(UserError):
            m.action_set_to_draft()
        self.assertEqual(m.state, 'revoked')
        self.assertEqual(m.collection_count, 1)
        self.assertEqual(m.last_collection_date, date(2026, 5, 1))

    def test_unused_revoked_mandate_cannot_reuse_signed_reference(self):
        m = self._make_mandate()
        m.action_revoke()
        with self.assertRaisesRegex(UserError, 'same reference'):
            m.action_set_to_draft()
        self.assertEqual(m.state, 'revoked')

    # ---- amendment trail ----

    def test_iban_change_on_active_mandate_creates_amendment(self):
        m = self._make_mandate()
        old_iban = m.debtor_iban
        self.assertFalse(m.amendment_ids)
        new_iban = 'DE89370400440532013000'
        m.write({'debtor_iban': new_iban})
        self.assertEqual(len(m.amendment_ids), 1)
        amendment = m.amendment_ids
        self.assertEqual(amendment.amendment_type, 'iban')
        self.assertEqual(amendment.old_value, old_iban)
        self.assertEqual(amendment.new_value, m.debtor_iban)
        # The rendering helper must expose the original IBAN so the next
        # collection can emit OrgnlDbtrAcct under AmdmntInfDtls.
        details = m._eh_latest_amendment_for_rendering()
        self.assertEqual(details.get('original_iban'), old_iban)

    def test_scheme_change_requires_new_mandate(self):
        m = self._make_mandate()
        with self.assertRaisesRegex(UserError, 'new mandate'):
            m.write({'local_instrument': 'B2B'})
        self.assertFalse(m.amendment_ids)

    def test_never_collected_mandate_expires_from_signature_date(self):
        m = self._make_mandate(signature_date=date(2020, 1, 1))
        self.Mandate._cron_expire_dormant()
        m.invalidate_recordset(['state'])
        self.assertEqual(m.state, 'expired')

    def test_b2b_activation_requires_business_and_bank_confirmation(self):
        consumer = self._make_mandate(
            state='draft', local_instrument='B2B',
            b2b_bank_confirmed=True,
        )
        with self.assertRaisesRegex(UserError, 'business debtor'):
            consumer.action_activate()
        business = self.env['res.partner'].create({
            'name': 'B2B Debtor GmbH', 'vat': 'DE123456788',
        })
        mandate = self._make_mandate(
            mandate_id='MNDT-B2B-001', state='draft',
            partner_id=business.id, local_instrument='B2B',
        )
        with self.assertRaisesRegex(UserError, 'bank confirmation'):
            mandate.action_activate()
        mandate.b2b_bank_confirmed = True
        mandate.action_activate()
        self.assertEqual(mandate.state, 'active')

    def test_b2b_business_debtor_without_vat_can_be_confirmed(self):
        """The B2B scheme needs a non-consumer debtor, not a VAT number: a
        business below the VAT threshold is confirmed on the mandate."""
        business = self.env['res.partner'].create({
            'name': 'Muster GmbH (no VAT)',
        })
        self.assertFalse(business.is_company)
        mandate = self._make_mandate(
            mandate_id='MNDT-B2B-NOVAT', state='draft',
            partner_id=business.id, local_instrument='B2B',
            b2b_bank_confirmed=True,
        )
        with self.assertRaisesRegex(UserError, 'business debtor'):
            mandate.action_activate()
        mandate.b2b_business_debtor_confirmed = True
        mandate.action_activate()
        self.assertEqual(mandate.state, 'active')
        # The confirmation is signed mandate identity once active.
        manager = self.env['res.users'].create({
            'name': 'SEPA DD B2B manager',
            'login': 'eh_sepa_dd_b2b_manager',
            'email': 'eh_sepa_dd_b2b_manager@example.com',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('eh_account_base.group_eh_manager').id,
            ])],
        })
        with self.assertRaisesRegex(AccessError, 'immutable'):
            mandate.with_user(manager).write({
                'b2b_business_debtor_confirmed': False,
            })
        self.assertTrue(mandate.b2b_business_debtor_confirmed)

    def test_upgrade_keeps_signed_b2b_mandates_eligible(self):
        """An active Odoo 19 B2B mandate whose debtor has no VAT number stays
        collectable instead of blocking every batch that contains it."""
        business = self.env['res.partner'].create({
            'name': 'Legacy B2B debtor (no VAT)',
        })
        active = self._make_mandate(
            mandate_id='MNDT-B2B-LEGACY', partner_id=business.id,
            local_instrument='B2B', b2b_bank_confirmed=True,
        )
        draft = self._make_mandate(
            mandate_id='MNDT-B2B-LEGACY-DRAFT', state='draft',
            partner_id=business.id, local_instrument='B2B',
            b2b_bank_confirmed=True,
        )
        with self.assertRaisesRegex(UserError, 'business debtor'):
            active._eh_assert_scheme_eligibility()
        self.env.flush_all()
        path = (
            Path(__file__).parents[1] / 'migrations' / '20.0.1.2.0'
            / 'post-migration.py'
        )
        spec = spec_from_file_location('eh_sepa_dd_b2b_migration_test', path)
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        migration.migrate(self.env.cr, '19.0.1.2.0')
        self.env.invalidate_all()
        self.assertTrue(active.b2b_business_debtor_confirmed)
        self.assertTrue(active._eh_assert_scheme_eligibility())
        # A draft was never proven a business; it confirms at activation.
        self.assertFalse(draft.b2b_business_debtor_confirmed)

    def test_debtor_agent_change_creates_amendment_and_renders_smnda(self):
        # A debtor bank move changes the debtor BIC (agent). The scheme
        # requires the next collection to carry
        # OrgnlDbtrAcct/Id/Othr/Id=SMNDA
        # (same mandate, new debtor agent). Before the fix this change was
        # not recorded and the rendering helper never set
        # same_mandate_new_debtor_agent, so SMNDA was dead code.
        m = self._make_mandate(debtor_bic='BNPAFRPP')
        self.assertFalse(m.amendment_ids)
        m.write({'debtor_bic': 'DEUTDEFF'})
        self.assertEqual(len(m.amendment_ids), 1)
        amendment = m.amendment_ids
        self.assertEqual(amendment.amendment_type, 'agent')
        details = m._eh_latest_amendment_for_rendering()
        self.assertTrue(details.get('same_mandate_new_debtor_agent'))

    def test_noop_iban_write_creates_no_amendment(self):
        m = self._make_mandate()
        m.write({'debtor_iban': m.debtor_iban})
        self.assertFalse(m.amendment_ids)

    def test_iban_change_on_draft_mandate_creates_no_amendment(self):
        m = self._make_mandate(state='draft')
        m.write({'debtor_iban': 'DE89370400440532013000'})
        self.assertFalse(m.amendment_ids)
