# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Browser tour run for the standard cost card register (IFRS 10/10 UI layer).

Runs the eh_costing_test_tour in a real headless Chrome via HttpCase.
The eh_tour tag keeps browser cycles out of the default per-module runs;
the matrix runner selects them with --tours (test-tags eh_tour).
"""

from odoo.tests import HttpCase, tagged


@tagged('eh_tour', 'eh_account_costing', 'post_install', '-at_install')
class TestCostingTour(HttpCase):

    def test_cost_card_create_tour(self):
        before = self.env['eh.cost.card'].search([])
        # The accountant module reparents the core finance sections
        # under its own root app, so the tour opens the record action
        # instead of a fixed app tile. Assert here what that tile step
        # used to imply: the menu is still bound to the action the tour
        # opens and still filed under the Accounting section the
        # tour walks back through.
        menu = self.env.ref('eh_account_costing.menu_eh_cost_card')
        action = self.env.ref('eh_account_costing.action_eh_cost_card')
        section = self.env.ref('account.menu_finance_entries')
        self.assertEqual(menu.action, action)
        self.assertTrue(menu.parent_path.startswith(section.parent_path))
        self.start_tour(
            '/odoo/action-eh_account_costing.action_eh_cost_card',
            'eh_costing_test_tour',
            login='admin',
        )
        card = self.env['eh.cost.card'].search([]) - before
        self.assertEqual(len(card), 1,
                         'tour did not create the cost card record')
        self.assertEqual(card.item_name, 'Assembly line output')
        self.assertAlmostEqual(card.normal_capacity, 1200.0, places=2)
        self.assertNotEqual(card.name, '/',
                            'cost card sequence was not assigned on create')
        self.assertEqual(card.state, 'draft')
