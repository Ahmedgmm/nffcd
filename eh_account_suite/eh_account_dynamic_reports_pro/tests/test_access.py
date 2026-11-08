# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Role matrix for the Pro models after the ir.access conversion.

Odoo 20 replaced ir.model.access and ir.rule with ir.access rows, and the
loader no longer warns about a model without any permission row. These
checks pin the per-role operations the 19 ACLs granted, plus the company
and owner restrictions, so a conversion slip surfaces as a failure.
"""

from odoo.tests import TransactionCase, new_test_user, tagged


@tagged(
    'eh_account_dynamic_reports_pro', 'integration',
    'post_install', '-at_install',
)
class TestProAccessMatrix(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        cls.plain = new_test_user(
            cls.env, login='eh_pro_acl_plain',
            groups='base.group_user', company_id=company.id,
        )
        cls.eh_user = new_test_user(
            cls.env, login='eh_pro_acl_user',
            groups='base.group_user,eh_account_base.group_eh_user',
            company_id=company.id,
        )
        cls.eh_manager = new_test_user(
            cls.env, login='eh_pro_acl_manager',
            groups='base.group_user,eh_account_base.group_eh_manager',
            company_id=company.id,
        )

    def _operations(self, model_name, user):
        model = self.env[model_name].with_user(user).browse()
        return {
            operation for operation in ('read', 'write', 'create', 'unlink')
            if model.has_access(operation)
        }

    def test_role_operations_match_the_19_acls(self):
        everything = {'read', 'write', 'create', 'unlink'}
        expected = {
            'eh.report.builder': (
                {'read'}, everything,
            ),
            'eh.report.builder.line': (
                {'read'}, everything,
            ),
            'eh.report.forecast': (
                {'read', 'write', 'create'}, everything,
            ),
            'eh.report.forecast.result': (
                {'read', 'create', 'unlink'}, {'read', 'create', 'unlink'},
            ),
            'eh.report.schedule': (
                {'read', 'write', 'create'}, everything,
            ),
        }
        for model_name, (user_ops, manager_ops) in expected.items():
            with self.subTest(model=model_name):
                self.assertEqual(
                    self._operations(model_name, self.plain), set(),
                )
                self.assertEqual(
                    self._operations(model_name, self.eh_user), user_ops,
                )
                self.assertEqual(
                    self._operations(model_name, self.eh_manager),
                    manager_ops,
                )

    def test_company_restriction_hides_foreign_builder(self):
        foreign = self.env['res.company'].create({
            'name': 'EH Pro ACL Foreign Company',
        })
        self.eh_manager.write({
            'company_ids': [(4, foreign.id)],
        })
        builder = self.env['eh.report.builder'].create({
            'name': 'Foreign builder',
            'code': 'eh_pro_acl_foreign',
            'company_id': foreign.id,
        })
        home = self.env.company
        self.assertFalse(
            builder.with_user(self.eh_user).has_access('read'),
        )
        self.assertFalse(
            builder.with_user(self.eh_manager).with_context(
                allowed_company_ids=[home.id],
            ).has_access('read'),
        )
        self.assertTrue(
            builder.with_user(self.eh_manager).with_context(
                allowed_company_ids=[foreign.id],
            ).has_access('write'),
        )
