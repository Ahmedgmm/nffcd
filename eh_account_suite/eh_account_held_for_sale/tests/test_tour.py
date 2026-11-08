# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Browser tour run for the held-for-sale register (IFRS 10/10 UI layer).

Runs the eh_held_for_sale_test_tour in a real headless Chrome via HttpCase.
The eh_tour tag keeps browser cycles out of the default per-module runs;
the matrix runner selects them with --tours (test-tags eh_tour).
"""

from odoo.tests import HttpCase, tagged


@tagged('eh_tour', 'eh_account_held_for_sale', 'post_install', '-at_install')
class TestHeldForSaleTour(HttpCase):

    def test_held_for_sale_create_tour(self):
        before = self.env['eh.held.for.sale'].search([])
        # The accountant module reparents the core finance sections
        # under its own root app, so the tour opens the record action
        # instead of a fixed app tile. Assert here what that tile step
        # used to imply: the menu is still bound to the action the tour
        # opens and still filed under the Accounting section the
        # tour walks back through.
        menu = self.env.ref('eh_account_held_for_sale.menu_eh_held_for_sale')
        action = self.env.ref(
            'eh_account_held_for_sale.action_eh_held_for_sale')
        section = self.env.ref('account.menu_finance_entries')
        self.assertEqual(menu.action, action)
        self.assertTrue(menu.parent_path.startswith(section.parent_path))
        self.start_tour(
            '/odoo/action-eh_account_held_for_sale.action_eh_held_for_sale',
            'eh_held_for_sale_test_tour',
            login='admin',
        )
        item = self.env['eh.held.for.sale'].search([]) - before
        self.assertEqual(len(item), 1,
                         'tour did not create the held-for-sale record')
        self.assertEqual(item.description, 'Northgate retail store')
        self.assertAlmostEqual(item.carrying_amount, 50000.0, places=2)
        self.assertAlmostEqual(item.fair_value_less_costs, 42000.0, places=2)
        self.assertAlmostEqual(item.writedown, 8000.0, places=2)
        self.assertEqual(item.state, 'draft')
        self.assertNotEqual(item.name, '/',
                            'sequence did not assign a reference')
