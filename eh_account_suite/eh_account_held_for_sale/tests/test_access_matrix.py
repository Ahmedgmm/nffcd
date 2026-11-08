# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Access matrix pinned per role after the ir.access conversion.

The 19.0 access control rows and the global company isolation rules were
converted into ir.access permission rows and group-less restrictions. These
tests pin the effective role matrix and the company isolation so the
converted rows stay equivalent to the original access design.
"""

from odoo.tests import new_test_user, tagged

from odoo.addons.eh_account_base.tests.common import (
    EhAccountIntegrationTestCase,
)

_OPERATIONS = ('read', 'write', 'create', 'unlink')

# Effective operations per role, as granted by the 19.0 ACL rows.
_MATRIX = {
    'eh.held.for.sale': {
        'user': {'read', 'write', 'create'},
        'manager': set(_OPERATIONS),
        'auditor': {'read'},
        'internal': set(),
    },
    'eh.disposal.group': {
        'user': {'read', 'write', 'create'},
        'manager': set(_OPERATIONS),
        'auditor': {'read'},
        'internal': set(),
    },
    'eh.disposal.group.line': {
        'user': set(_OPERATIONS),
        'manager': set(_OPERATIONS),
        'auditor': {'read'},
        'internal': set(),
    },
}


@tagged('eh_account_held_for_sale', 'post_install', '-at_install')
class TestHeldForSaleAccessMatrix(EhAccountIntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.asset = cls._ensure_account(
            cls.env, '1700', 'Assets Held for Sale', 'asset_current')
        cls.impairment = cls._ensure_account(
            cls.env, '5170', 'Held-for-sale Impairment', 'expense')
        cls.other_company = cls.env['res.company'].create({
            'name': 'HFS Access Other Company',
        })
        common = {
            'company_id': cls.company.id,
            'company_ids': [(6, 0, cls.company.ids)],
        }
        cls.roles = {
            'user': new_test_user(
                cls.env, 'eh_hfs_acl_user',
                groups='base.group_user,eh_account_base.group_eh_user',
                **common),
            'manager': new_test_user(
                cls.env, 'eh_hfs_acl_manager',
                groups='base.group_user,eh_account_base.group_eh_manager',
                **common),
            'auditor': new_test_user(
                cls.env, 'eh_hfs_acl_auditor',
                groups='base.group_user,eh_account_base.group_eh_auditor',
                **common),
            'internal': new_test_user(
                cls.env, 'eh_hfs_acl_internal',
                groups='base.group_user', **common),
        }

    def test_role_matrix_matches_access_design(self):
        for model, roles in _MATRIX.items():
            for role, allowed in roles.items():
                records = self.env[model].with_user(self.roles[role]).browse()
                for operation in _OPERATIONS:
                    with self.subTest(model=model, role=role,
                                      operation=operation):
                        self.assertEqual(
                            records.has_access(operation),
                            operation in allowed,
                        )

    def test_every_model_has_company_restriction_on_all_operations(self):
        for model in _MATRIX:
            restrictions = self.env['ir.access'].search([
                ('model_id.model', '=', model),
                ('group_id', '=', False),
            ])
            with self.subTest(model=model):
                self.assertEqual(len(restrictions), 1)
                self.assertEqual(restrictions.operation, 'crud')
                self.assertIn('company_ids', restrictions.domain)

    def test_other_company_records_are_isolated(self):
        own_item = self.env['eh.held.for.sale'].create({
            'name': '/', 'carrying_amount': 1000.0,
            'fair_value_less_costs': 800.0,
        })
        foreign_item = self.env['eh.held.for.sale'].create({
            'name': '/', 'carrying_amount': 1000.0,
            'fair_value_less_costs': 800.0,
            'company_id': self.other_company.id,
        })
        own_group = self.env['eh.disposal.group'].create({
            'name': '/', 'fair_value_less_costs': 800.0,
            'line_ids': [(0, 0, {
                'name': 'Own member', 'carrying_amount': 1000.0,
                'account_id': self.asset.id,
            })],
        })
        foreign_group = self.env['eh.disposal.group'].create({
            'name': '/', 'fair_value_less_costs': 800.0,
            'company_id': self.other_company.id,
            'line_ids': [(0, 0, {
                'name': 'Foreign member', 'carrying_amount': 1000.0,
            })],
        })
        for role in ('user', 'manager', 'auditor'):
            user = self.roles[role]
            with self.subTest(role=role):
                self.assertTrue(own_item.with_user(user).has_access('read'))
                self.assertFalse(
                    foreign_item.with_user(user).has_access('read'))
                self.assertTrue(own_group.with_user(user).has_access('read'))
                self.assertFalse(
                    foreign_group.with_user(user).has_access('read'))
                self.assertTrue(
                    own_group.line_ids.with_user(user).has_access('read'))
                self.assertFalse(
                    foreign_group.line_ids.with_user(user).has_access('read'))
                visible = self.env['eh.held.for.sale'].with_user(
                    user).search([('id', 'in', (own_item | foreign_item).ids)])
                self.assertEqual(visible, own_item)
                visible_lines = self.env['eh.disposal.group.line'].with_user(
                    user).search([('id', 'in', (
                        own_group.line_ids | foreign_group.line_ids).ids)])
                self.assertEqual(visible_lines, own_group.line_ids)
