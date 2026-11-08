# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Browser tour run for the fixed asset register (IFRS 10/10 UI layer).

Runs the eh_assets_test_tour in a real headless Chrome via HttpCase.
The eh_tour tag keeps browser cycles out of the default per-module runs;
the matrix runner selects them with --tours (test-tags eh_tour).
"""

from odoo.tests import HttpCase, tagged


@tagged('eh_tour', 'eh_account_assets_pro', 'post_install', '-at_install')
class TestAssetTour(HttpCase):

    def test_asset_create_tour(self):
        # The form's only required field without a default is the category
        # many2one; seed a deterministic match for the tour's autocomplete.
        category = self.env['eh.asset.category'].create({
            'name': 'Tour Plant Category',
        })
        before = self.env['eh.asset'].search([])
        # The accountant module reparents the core finance sections
        # under its own root app, so the tour opens the record action
        # instead of a fixed app tile. Assert here what that tile step
        # used to imply: the menu is still bound to the action the tour
        # opens and still filed under the Accounting section the
        # tour walks back through.
        menu = self.env.ref('eh_account_assets_pro.menu_eh_asset_all')
        action = self.env.ref('eh_account_assets_pro.action_eh_asset')
        section = self.env.ref('account.menu_finance_entries')
        self.assertEqual(menu.action, action)
        self.assertTrue(menu.parent_path.startswith(section.parent_path))
        self.start_tour(
            '/odoo/action-eh_account_assets_pro.action_eh_asset',
            'eh_assets_test_tour',
            login='admin',
        )
        asset = self.env['eh.asset'].search([]) - before
        self.assertEqual(len(asset), 1,
                         'tour did not create the asset record')
        self.assertEqual(asset.code, 'TOUR-FA-01')
        self.assertEqual(asset.category_id, category)
        self.assertAlmostEqual(asset.acquisition_cost, 12000.0, places=2)
        self.assertNotEqual(asset.name, '/',
                            'sequence did not assign the asset name')
        self.assertEqual(asset.state, 'draft')
        self.assertTrue(asset.depreciation_line_ids,
                        'Compute Schedule did not build schedule lines')
