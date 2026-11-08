# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Access matrix of the IAS 7.43 non-cash register on Odoo 20 ir.access.

Odoo 20 replaced ir.model.access and ir.rule with ir.access and no longer
warns about a model without permission rows, so the converted rows are
pinned here per role: suite users read, create and update, managers also
delete, auditors only read, other internal users see nothing, and every
operation stays inside the user's allowed companies.
"""

from odoo.tests import new_test_user, tagged
from odoo.tests.common import TransactionCase

OPERATIONS = ('read', 'write', 'create', 'unlink')


@tagged('eh_account_dynamic_reports', 'post_install', '-at_install')
class TestNoncashRegisterAccess(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env['res.company'].create({
            'name': 'Non-cash register isolation company',
        })
        both = [(6, 0, [cls.company.id, cls.other_company.id])]
        cls.users = {
            role: new_test_user(
                cls.env,
                login='eh_noncash_%s' % role,
                groups=groups,
                company_id=cls.company.id,
                company_ids=both,
            )
            for role, groups in (
                ('user', 'eh_account_base.group_eh_user'),
                ('manager', 'eh_account_base.group_eh_manager'),
                ('auditor', 'eh_account_base.group_eh_auditor'),
                ('internal', 'base.group_user'),
            )
        }
        Register = cls.env['eh.noncash.transaction']
        cls.own_entry = Register.create({
            'name': 'Lease in the main company',
            'amount': 500.0,
            'kind': 'lease',
            'company_id': cls.company.id,
        })
        cls.other_entry = Register.create({
            'name': 'Lease in the isolation company',
            'amount': 700.0,
            'kind': 'lease',
            'company_id': cls.other_company.id,
        })

    def _register(self, role):
        return self.env['eh.noncash.transaction'].with_user(
            self.users[role],
        ).with_context(allowed_company_ids=[self.company.id])

    def test_model_permissions_per_role(self):
        expected = {
            'user': {'read', 'write', 'create'},
            'manager': set(OPERATIONS),
            'auditor': {'read'},
            'internal': set(),
        }
        for role, allowed in expected.items():
            Register = self._register(role)
            for operation in OPERATIONS:
                with self.subTest(role=role, operation=operation):
                    self.assertEqual(
                        Register.browse().has_access(operation),
                        operation in allowed,
                    )

    def test_company_restriction_applies_to_every_operation(self):
        for role in ('user', 'manager', 'auditor'):
            Register = self._register(role)
            with self.subTest(role=role):
                self.assertEqual(
                    Register.search([
                        ('id', 'in', (self.own_entry | self.other_entry).ids),
                    ]),
                    self.own_entry.with_env(Register.env),
                )
                foreign = self.other_entry.with_env(Register.env)
                for operation in OPERATIONS:
                    self.assertFalse(foreign.has_access(operation))
        manager_register = self._register('manager')
        self.assertTrue(
            self.own_entry.with_env(manager_register.env).has_access('unlink'),
        )
