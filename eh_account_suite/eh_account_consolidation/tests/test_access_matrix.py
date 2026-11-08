# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Model-level access per role after the Odoo 20 ir.access conversion.

Odoo 20 replaced ir.model.access and ir.rule with ir.access rows, and the
conversion folded rows covered by implied groups (the manager implies the
user). This pins the effective operations of every consolidation model for
each role to the matrix the module granted before the conversion, so a row
lost or widened by the conversion fails here.
"""

from odoo.tests import TransactionCase, new_test_user, tagged

_OPERATIONS = ('read', 'write', 'create', 'unlink')

# Effective operations per model: (user, manager, auditor), as "crud" subsets.
_MATRIX = {
    'eh.consol.entity': ('r', 'crud', 'r'),
    'eh.consol.member': ('r', 'crud', 'r'),
    'eh.consol.run': ('cru', 'crud', 'r'),
    'eh.consol.run.line': ('r', 'crud', 'r'),
    'eh.consol.elimination': ('cru', 'crud', 'r'),
    'eh.consol.elimination.line': ('crud', 'crud', 'r'),
    'eh.consol.unrealised.profit': ('cru', 'crud', 'r'),
    'eh.consol.acquisition.equity.component': ('r', 'crud', 'r'),
    'eh.consol.equity.rollforward': ('cru', 'crud', 'r'),
    'eh.consol.disposal.event': ('r', 'r', 'r'),
    'eh.consol.trial.balance': ('r', 'r', 'r'),
}

_LETTER = {'read': 'r', 'write': 'u', 'create': 'c', 'unlink': 'd'}


@tagged('eh_account_consolidation', 'post_install', '-at_install')
class TestConsolidationAccessMatrix(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.roles = (
            new_test_user(
                cls.env, login='consol_access_user',
                groups='base.group_user,eh_account_base.group_eh_user',
            ),
            new_test_user(
                cls.env, login='consol_access_manager',
                groups='base.group_user,eh_account_base.group_eh_manager',
            ),
            new_test_user(
                cls.env, login='consol_access_auditor',
                groups='base.group_user,eh_account_base.group_eh_auditor',
            ),
        )
        cls.internal = new_test_user(
            cls.env, login='consol_access_internal', groups='base.group_user',
        )

    def test_role_operations_match_the_granted_matrix(self):
        for model_name, grants in _MATRIX.items():
            for user, granted in zip(self.roles, grants):
                Model = self.env[model_name].with_user(user).browse()
                for operation in _OPERATIONS:
                    with self.subTest(
                        model=model_name, user=user.login,
                        operation=operation,
                    ):
                        self.assertEqual(
                            Model.has_access(operation),
                            _LETTER[operation] in granted,
                        )

    def test_plain_internal_user_has_no_access(self):
        for model_name in _MATRIX:
            Model = self.env[model_name].with_user(self.internal).browse()
            for operation in _OPERATIONS:
                with self.subTest(model=model_name, operation=operation):
                    self.assertFalse(Model.has_access(operation))

    def test_every_model_keeps_its_company_closure_restriction(self):
        restrictions = self.env['ir.access'].search([
            ('model_id.model', 'in', list(_MATRIX)),
            ('group_id', '=', False),
        ])
        by_model = {}
        for restriction in restrictions:
            by_model.setdefault(restriction.model_id.model, []).append(
                restriction,
            )
        for model_name in _MATRIX:
            with self.subTest(model=model_name):
                rows = by_model.get(model_name, [])
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].operation, 'crud')
                self.assertEqual(
                    rows[0].domain,
                    "[('eh_company_scope_allowed', '=', True)]",
                )
