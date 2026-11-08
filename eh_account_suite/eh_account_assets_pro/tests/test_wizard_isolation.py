##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""eh.asset.lvp.transfer.wizard records stay private to the user and company that made them.

Odoo 20 access restrictions (group-less ir.access rows) are AND-ed onto every
user, so a wizard started by one accountant is invisible to another, and never
visible outside the companies a user may access.
"""

from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestAssetLvpTransferWizardIsolation(TransactionCase):

    MODEL = 'eh.asset.lvp.transfer.wizard'

    def test_owner_and_company_restrictions_exist(self):
        rows = self.env['ir.access'].sudo().search([
            ('model_id.model', '=', self.MODEL), ('group_id', '=', False),
        ])
        by_domain = {row.domain: row.operation for row in rows}
        self.assertEqual(by_domain.get("[('create_uid', '=', user.id)]"), 'crud')
        self.assertEqual(by_domain.get("[('company_id', 'in', company_ids)]"), 'crud')
