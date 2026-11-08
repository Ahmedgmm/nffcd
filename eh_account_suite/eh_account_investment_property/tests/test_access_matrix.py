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

# Effective operations per role, as granted by the 19.0 ACL rows. The
# transfer audit trail and the depreciation history are engine written:
# only the manager may create a transfer row, and nobody edits either.
_MATRIX = {
    'eh.investment.property': {
        'user': {'read', 'write', 'create'},
        'manager': set(_OPERATIONS),
        'auditor': {'read'},
        'internal': set(),
    },
    'eh.investment.property.transfer': {
        'user': {'read'},
        'manager': {'read', 'create'},
        'auditor': {'read'},
        'internal': set(),
    },
    'eh.investment.property.depreciation': {
        'user': {'read'},
        'manager': {'read'},
        'auditor': {'read'},
        'internal': set(),
    },
}


@tagged('eh_account_investment_property', 'post_install', '-at_install')
class TestInvestmentPropertyAccessMatrix(EhAccountIntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_company = cls.env['res.company'].create({
            'name': 'IP Access Other Company',
        })
        common = {
            'company_id': cls.company.id,
            'company_ids': [(6, 0, cls.company.ids)],
        }
        cls.roles = {
            'user': new_test_user(
                cls.env, 'eh_ip_acl_user',
                groups='base.group_user,eh_account_base.group_eh_user',
                **common),
            'manager': new_test_user(
                cls.env, 'eh_ip_acl_manager',
                groups='base.group_user,eh_account_base.group_eh_manager',
                **common),
            'auditor': new_test_user(
                cls.env, 'eh_ip_acl_auditor',
                groups='base.group_user,eh_account_base.group_eh_auditor',
                **common),
            'internal': new_test_user(
                cls.env, 'eh_ip_acl_internal',
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
        values = {
            'name': '/', 'model_basis': 'fair_value',
            'initial_cost': 500000.0, 'acquisition_date': '2026-01-01',
        }
        own = self.env['eh.investment.property'].create(dict(values))
        foreign = self.env['eh.investment.property'].create(dict(
            values, company_id=self.other_company.id))
        for role in ('user', 'manager', 'auditor'):
            user = self.roles[role]
            with self.subTest(role=role):
                self.assertTrue(own.with_user(user).has_access('read'))
                self.assertFalse(foreign.with_user(user).has_access('read'))
                visible = self.env['eh.investment.property'].with_user(
                    user).search([('id', 'in', (own | foreign).ids)])
                self.assertEqual(visible, own)
