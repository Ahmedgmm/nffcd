##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""eh.peppol.inbound.upload records stay private to the user and company that made them.

Odoo 20 access restrictions (group-less ir.access rows) are AND-ed onto every
user, so a wizard started by one accountant is invisible to another, and never
visible outside the companies a user may access.
"""

import base64

from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestPeppolInboundUploadIsolation(TransactionCase):

    MODEL = 'eh.peppol.inbound.upload'

    def test_owner_and_company_restrictions_exist(self):
        rows = self.env['ir.access'].sudo().search([
            ('model_id.model', '=', self.MODEL), ('group_id', '=', False),
        ])
        by_domain = {row.domain: row.operation for row in rows}
        self.assertEqual(by_domain.get("[('create_uid', '=', user.id)]"), 'crud')
        self.assertEqual(by_domain.get("[('company_id', 'in', company_ids)]"), 'crud')

    def test_other_user_cannot_see_the_wizard(self):
        groups = 'base.group_user,eh_account_base.group_eh_user'
        first = new_test_user(self.env, login='eh_iso_first', groups=groups)
        second = new_test_user(self.env, login='eh_iso_second', groups=groups)
        Wizard = self.env[self.MODEL]
        wizard = Wizard.with_user(first).create({'xml_file': base64.b64encode(b'<Invoice/>').decode(), 'filename': 'x.xml'})
        self.assertTrue(Wizard.with_user(first).search([('id', '=', wizard.id)]))
        self.assertFalse(Wizard.with_user(second).search([('id', '=', wizard.id)]))
        self.assertFalse(wizard.with_user(second).has_access('read'))
