# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Browser tour run for the revenue contract (IFRS 10/10 UI layer).

Runs the eh_revenue_test_tour in a real headless Chrome via HttpCase.
The eh_tour tag keeps browser cycles out of the default per-module runs;
the matrix runner selects them with --tours (test-tags eh_tour).
"""

from odoo.tests import HttpCase, tagged


@tagged('eh_tour', 'eh_account_revenue', 'post_install', '-at_install')
class TestRevenueTour(HttpCase):

    def test_revenue_contract_create_tour(self):
        # The tour selects the customer through the many2one autocomplete;
        # seed an exact-match partner so the first dropdown hit is a real
        # record and never the quick-create option.
        self.env['res.partner'].create({'name': 'Tour Customer'})
        before = self.env['eh.revenue.contract'].search([])
        # The accountant module reparents the core finance sections
        # under its own root app, so the tour opens the record action
        # instead of a fixed app tile. Assert here what that tile step
        # used to imply: the menu is still bound to the action the tour
        # opens and still filed under the Accounting section the
        # tour walks back through.
        menu = self.env.ref('eh_account_revenue.menu_eh_revenue_contract')
        action = self.env.ref('eh_account_revenue.action_eh_revenue_contract')
        section = self.env.ref('account.menu_finance_entries')
        self.assertEqual(menu.action, action)
        self.assertTrue(menu.parent_path.startswith(section.parent_path))
        self.start_tour(
            '/odoo/action-eh_account_revenue.action_eh_revenue_contract',
            'eh_revenue_test_tour',
            login='admin',
        )
        contract = self.env['eh.revenue.contract'].search([]) - before
        self.assertEqual(len(contract), 1,
                         'tour did not create the revenue contract record')
        self.assertEqual(contract.partner_id.name, 'Tour Customer')
        self.assertAlmostEqual(contract.transaction_price, 5000.0, places=2)
        self.assertEqual(contract.state, 'draft')
        self.assertTrue(contract.name.startswith('REV/'),
                        'sequence did not assign the contract reference')
