# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""The IAS 37 disclosure wizard and its lines stay with their creator.

Odoo 20 adds no implicit creator restriction to transient models: without
an explicit restriction any EH user could read, change or delete another
company's contingent-liability figures and litigation notes while that
user's disclosure wizard is still alive.
"""

from odoo.exceptions import AccessError
from odoo.tests import tagged

from odoo.addons.eh_account_base.tests.common import (
    EhAccountIntegrationTestCase,
)


@tagged('eh_account_provisions', 'post_install', '-at_install')
class TestProvisionDisclosureIsolation(EhAccountIntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env['res.company'].create({
            'name': 'Disclosure Isolation Co B',
        })

        def user(login, company):
            return cls.env['res.users'].create({
                'name': login,
                'login': login,
                'company_id': company.id,
                'company_ids': [(6, 0, company.ids)],
                'group_ids': [(6, 0, [
                    cls.env.ref('base.group_user').id,
                    cls.env.ref('eh_account_base.group_eh_user').id,
                ])],
            })

        cls.user_a = user('disclosure_isolation_a', cls.company)
        cls.user_a2 = user('disclosure_isolation_a2', cls.company)
        cls.user_b = user('disclosure_isolation_b', cls.company_b)
        provision_b = cls.env['eh.provision'].sudo().create({
            'name': '/',
            'company_id': cls.company_b.id,
            'classification': 'contingent_liability',
            'best_estimate': 987654.0,
        })
        cls.wizard_b = cls.env['eh.provision.disclosure.wizard'].with_user(
            cls.user_b).create({'company_id': cls.company_b.id})
        cls.line_b = cls.env['eh.provision.disclosure.line'].with_user(
            cls.user_b).create({
                'wizard_id': cls.wizard_b.id,
                'provision_id': provision_b.id,
                'name': 'Secret litigation B',
                'company_id': cls.company_b.id,
                'currency_id': cls.company_b.currency_id.id,
                'contingent_estimate': 987654.0,
                'nature': 'Class action about product X',
            })

    def test_other_company_cannot_read_change_or_delete(self):
        Line = self.env['eh.provision.disclosure.line'].with_user(self.user_a)
        Wizard = self.env['eh.provision.disclosure.wizard'].with_user(
            self.user_a)
        self.assertFalse(Line.search_read([], ['contingent_estimate']))
        self.assertFalse(Wizard.search([]))
        with self.assertRaises(AccessError):
            self.line_b.with_user(self.user_a).read(['contingent_estimate'])
        with self.assertRaises(AccessError):
            self.line_b.with_user(self.user_a).write({'nature': 'tampered'})
        with self.assertRaises(AccessError):
            self.wizard_b.with_user(self.user_a).unlink()
        self.assertTrue(self.wizard_b.exists())
        self.assertEqual(self.line_b.nature, 'Class action about product X')

    def test_same_company_user_cannot_reach_another_users_wizard(self):
        wizard = self.env['eh.provision.disclosure.wizard'].with_user(
            self.user_a).create({'company_id': self.company.id})
        self.assertEqual(
            self.env['eh.provision.disclosure.wizard'].with_user(
                self.user_a).search([('id', '=', wizard.id)]),
            wizard,
        )
        self.assertFalse(
            self.env['eh.provision.disclosure.wizard'].with_user(
                self.user_a2).search([('id', '=', wizard.id)]))
        with self.assertRaises(AccessError):
            wizard.with_user(self.user_a2).unlink()

    def test_creator_keeps_full_access(self):
        line = self.line_b.with_user(self.user_b)
        self.assertEqual(line.read(['contingent_estimate'])[0][
            'contingent_estimate'], 987654.0)
        line.write({'nature': 'Updated by creator'})
        self.assertEqual(self.line_b.nature, 'Updated by creator')
