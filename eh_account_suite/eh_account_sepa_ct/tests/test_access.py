# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Per-role access matrix of the SEPA Credit Transfer models.

The loader no longer warns about a model without any ir.access permission
row, so each role's model-level rights and the company isolation
restriction are asserted here.
"""

from odoo.tests import TransactionCase, tagged


OPERATIONS = ('read', 'write', 'create', 'unlink')


@tagged('eh_account_sepa_ct', 'post_install', '-at_install')
class TestSepaCtAccess(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.users = {
            role: cls.env['res.users'].create({
                'name': 'SEPA CT %s' % role,
                'login': 'eh_sepa_ct_access_%s' % role,
                'email': 'eh_sepa_ct_access_%s@example.com' % role,
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

    def test_originator_access(self):
        self._assert_matrix('eh.sepa.originator', {
            'user': {'read'},
            'manager': set(OPERATIONS),
            'auditor': set(),
        })

    def test_export_access(self):
        self._assert_matrix('eh.sepa.export', {
            'user': set(),
            'manager': {'read', 'write'},
            'auditor': {'read'},
        })

    def test_source_approval_access(self):
        self._assert_matrix('eh.sepa.ct.source.approval', {
            'user': set(),
            'manager': {'read'},
            'auditor': {'read'},
        })

    def test_every_model_has_a_company_restriction(self):
        for model in (
            'eh.sepa.originator',
            'eh.sepa.export',
            'eh.sepa.ct.source.approval',
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
