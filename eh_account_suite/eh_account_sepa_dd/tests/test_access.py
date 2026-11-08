# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Per-role access matrix of the SEPA Direct Debit models.

The loader no longer warns about a model without any ir.access permission
row, so each role's model-level rights and the company isolation
restriction are asserted here.
"""

from odoo.tests import TransactionCase, tagged


OPERATIONS = ('read', 'write', 'create', 'unlink')


@tagged('eh_account_sepa_dd', 'post_install', '-at_install')
class TestSepaDdAccess(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.users = {
            role: cls.env['res.users'].create({
                'name': 'SEPA DD %s' % role,
                'login': 'eh_sepa_dd_access_%s' % role,
                'email': 'eh_sepa_dd_access_%s@example.com' % role,
                'group_ids': [(6, 0, cls.env.ref(
                    'eh_account_base.group_eh_%s' % role,
                ).ids)],
            })
            for role in ('user', 'manager', 'auditor')
        }

    def _assert_matrix(self, model, expected):
        for role, allowed in expected.items():
            records = self.env[model].with_user(self.users[role]).browse()
            for operation in OPERATIONS:
                with self.subTest(model=model, role=role, operation=operation):
                    self.assertEqual(
                        records.has_access(operation),
                        operation in allowed,
                    )

    def test_creditor_access(self):
        self._assert_matrix('eh.sepa.creditor', {
            'user': {'read'},
            'manager': set(OPERATIONS),
            'auditor': set(),
        })

    def test_mandate_access(self):
        self._assert_matrix('eh.sepa.mandate', {
            'user': {'read', 'write', 'create'},
            'manager': set(OPERATIONS),
            'auditor': {'read'},
        })

    def test_mandate_amendment_access(self):
        self._assert_matrix('eh.sepa.mandate.amendment', {
            'user': {'read'},
            'manager': {'read'},
            'auditor': {'read'},
        })

    def test_export_access(self):
        self._assert_matrix('eh.sepa.dd.export', {
            'user': set(),
            'manager': {'read', 'write'},
            'auditor': {'read'},
        })

    def test_source_approval_access(self):
        self._assert_matrix('eh.sepa.dd.source.approval', {
            'user': set(),
            'manager': {'read'},
            'auditor': {'read'},
        })

    def test_every_model_has_a_company_restriction(self):
        for model in (
            'eh.sepa.creditor',
            'eh.sepa.mandate',
            'eh.sepa.mandate.amendment',
            'eh.sepa.dd.export',
            'eh.sepa.dd.source.approval',
        ):
            restrictions = self.env['ir.access'].sudo().search([
                ('model_id.model', '=', model),
                ('group_id', '=', False),
            ])
            with self.subTest(model=model):
                self.assertTrue(any(
                    access.operation == 'crud'
                    and 'company_ids' in (access.domain or '')
                    for access in restrictions
                ))
