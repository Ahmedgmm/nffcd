# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Headless-browser verification for the financial dashboard."""

from odoo.tests import HttpCase, tagged


@tagged('eh_tour', 'eh_account_dashboard', 'post_install', '-at_install')
class TestDashboardTour(HttpCase):

    def test_dashboard_menu_snapshot_refresh_tour(self):
        admin = self.env.ref('base.user_admin')
        admin.group_ids |= self.env.ref('eh_account_base.group_eh_user')

        # The section is filed in the Community finance root, or in
        # accountant's Accounting app once the suite applies the Enterprise
        # layout. Read the app from the menu tree the web client loads for
        # the tour user, pin it to one of those finance apps, and open it
        # the way a click on its home menu tile does; the tour then clicks
        # the section in that app's navbar.
        menu = self.env.ref('eh_account_dashboard.menu_eh_account_dashboard')
        self.assertEqual(
            menu.action,
            self.env.ref('eh_account_dashboard.action_eh_account_dashboard'),
        )
        menus = self.env['ir.ui.menu'].with_user(admin).load_menus(False)
        self.assertIn(menu.id, menus, 'the dashboard menu is not visible')
        app_id = menus[menu.id]['app_id']
        self.assertIn(app_id, menus['root']['children'])
        finance_apps = self.env.ref('account.menu_finance')
        accountant_app = self.env.ref(
            'accountant.menu_accounting', raise_if_not_found=False)
        if accountant_app:
            finance_apps |= accountant_app
        self.assertIn(app_id, finance_apps.ids)

        self.start_tour(
            '/odoo?menu_id=%d' % app_id,
            'eh_dashboard_test_tour',
            login='admin',
        )

        dashboard = self.env['eh.account.dashboard'].sudo().search([
            ('user_id', '=', admin.id),
            ('company_id', '=', admin.company_id.id),
        ])
        self.assertEqual(len(dashboard), 1)
        self.assertEqual(dashboard.user_id, admin)
        self.assertEqual(dashboard.company_id, admin.company_id)
