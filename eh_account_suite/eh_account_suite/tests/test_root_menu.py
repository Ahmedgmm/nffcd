##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""The database has exactly one app named Accounting, whatever the edition.

Community calls the finance app Invoicing. With the whole suite installed the
app is a full accounting department, so the root menu is renamed in place
(every submenu keeps its own xml id) and the uninstall hook puts Invoicing
back. The Enterprise accountant module brings its own Accounting app; the
suite then files its sections there and leaves the Community name alone, so
the customer never sees two apps named Accounting.
"""

from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.eh_account_suite.hooks import (
    COMMUNITY_ROOT_MENU_NAME,
    SUITE_ROOT_MENU_NAME,
    uninstall_hook,
)
from odoo.addons.eh_account_suite.tests.common import (
    ENTERPRISE_CORE_SECTIONS,
    accounting_app,
    build_enterprise_app,
    is_enterprise_layout,
    own_sections_under,
)


@tagged('post_install', '-at_install')
class TestRootMenuName(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.finance = cls.env.ref('account.menu_finance')
        cls.admin = cls.env.ref('base.user_admin')

    def _english_name(self, menu):
        return menu.with_context(lang='en_US').name

    def _enterprise_layout_with_a_stray_section(self):
        """Enterprise layout, with one suite section back under the finance
        root and the suite name on it: the state right after accountant is
        installed on a suite database, or after a module update files a
        section under the parent its XML declares."""
        host = build_enterprise_app(self.env)
        section = self.env.ref('eh_account_base.menu_eh_operations')
        section.parent_id = self.finance
        self.finance.with_context(lang='en_US').name = SUITE_ROOT_MENU_NAME
        return host, section

    def test_root_menu_is_accounting(self):
        self.assertEqual(
            self._english_name(accounting_app(self.env)), SUITE_ROOT_MENU_NAME)
        if is_enterprise_layout(self.env):
            # accountant already owns the Accounting app: no second one.
            self.assertEqual(
                self._english_name(self.finance), COMMUNITY_ROOT_MENU_NAME)

    def test_submenus_keep_their_parent(self):
        """The upstream sections continue to share the one Accounting app."""
        app = accounting_app(self.env)
        for xmlid in (
            'account.menu_finance_receivables',
            'account.menu_finance_payables',
            'account.menu_finance_entries',
            'account.menu_finance_reports',
            'account.menu_finance_configuration',
        ):
            child = self.env.ref(xmlid, raise_if_not_found=False)
            if child:
                self.assertEqual(child.parent_id, app, xmlid)

    def test_enterprise_layout_leaves_no_second_accounting_app(self):
        """Suite sections move into the Enterprise app, and the finance root,
        left with nothing a user can open, disappears from the web client."""
        host, section = self._enterprise_layout_with_a_stray_section()
        strays = own_sections_under(self.env, self.finance)
        self.assertIn(section, strays)
        core = self.env['ir.ui.menu'].browse([
            self.env.ref(xmlid).id for xmlid in ENTERPRISE_CORE_SECTIONS
        ])

        self.env['ir.ui.menu']._eh_sync_finance_app()

        self.assertEqual(strays.parent_id, host)
        self.assertFalse(own_sections_under(self.env, self.finance))
        self.assertEqual(core.parent_id, host)
        self.assertEqual(
            self._english_name(self.finance), COMMUNITY_ROOT_MENU_NAME)
        self.assertEqual(self._english_name(host), SUITE_ROOT_MENU_NAME)
        visible = self.env['ir.ui.menu'].with_user(self.admin)._visible_menu_ids()
        self.assertIn(host.id, visible)
        self.assertNotIn(self.finance.id, visible)

    def test_only_a_load_that_ran_module_data_resyncs(self):
        """Installing accountant after the suite, or updating any module, ends
        with a registry load that files the sections again; a plain worker
        start never writes menus."""
        host, section = self._enterprise_layout_with_a_stray_section()
        menus = self.env['ir.ui.menu']
        with patch.object(self.registry, 'updated_modules', []), \
                patch.object(self.registry, 'ready', False):
            menus._register_hook()
        self.assertEqual(section.parent_id, self.finance)
        with patch.object(self.registry, 'updated_modules', ['accountant']), \
                patch.object(self.registry, 'ready', True):
            menus._register_hook()
        self.assertEqual(section.parent_id, self.finance)
        with patch.object(self.registry, 'updated_modules', ['accountant']), \
                patch.object(self.registry, 'ready', False):
            menus._register_hook()
        self.assertEqual(section.parent_id, host)
        self.assertEqual(
            self._english_name(self.finance), COMMUNITY_ROOT_MENU_NAME)

    def test_removing_the_enterprise_app_hands_every_section_back(self):
        """Uninstalling accountant deletes its app. Odoo would promote each
        remaining child to a top-level app; the suite brings them home and
        the finance root is Accounting again."""
        host = build_enterprise_app(self.env)
        self.env['ir.ui.menu']._eh_sync_finance_app()
        children = self.env['ir.ui.menu'].with_context(
            active_test=False).search([('parent_id', '=', host.id)])
        self.assertTrue(own_sections_under(self.env, host))

        host.unlink()

        self.assertEqual(children.parent_id, self.finance)
        self.assertEqual(self._english_name(self.finance), SUITE_ROOT_MENU_NAME)

    def test_removing_both_apps_keeps_the_community_name(self):
        """When the suite leaves together with accountant, its uninstall hook
        has already restored Invoicing; deleting the Enterprise app must not
        rename it back."""
        host = build_enterprise_app(self.env)
        self.env['ir.ui.menu']._eh_sync_finance_app()
        children = self.env['ir.ui.menu'].with_context(
            active_test=False).search([('parent_id', '=', host.id)])
        with patch.object(
                self.registry, 'uninstalling_modules',
                {'eh_account_suite', 'accountant'}):
            host.unlink()
        self.assertEqual(children.parent_id, self.finance)
        self.assertEqual(
            self._english_name(self.finance), COMMUNITY_ROOT_MENU_NAME)

    def test_uninstall_restores_the_community_name(self):
        menu = self.env.ref('account.menu_finance')
        uninstall_hook(self.env)
        self.assertEqual(
            menu.with_context(lang='en_US').name, COMMUNITY_ROOT_MENU_NAME)

    def test_uninstall_leaves_a_foreign_name_alone(self):
        """An Enterprise or operator chosen name is not ours to reset."""
        menu = self.env.ref('account.menu_finance')
        menu.with_context(lang='en_US').name = 'Finance Department'
        uninstall_hook(self.env)
        self.assertEqual(
            menu.with_context(lang='en_US').name, 'Finance Department')

    def test_uninstall_returns_sections_to_their_declared_parent(self):
        """Without the suite nothing keeps them in the Enterprise app, and a
        later accountant uninstall would make each one a top-level app."""
        host = build_enterprise_app(self.env)
        self.env['ir.ui.menu']._eh_sync_finance_app()
        moved = own_sections_under(self.env, host)
        self.assertTrue(moved)
        core = self.env['ir.ui.menu'].browse([
            self.env.ref(xmlid).id for xmlid in ENTERPRISE_CORE_SECTIONS
        ])

        uninstall_hook(self.env)

        self.assertEqual(moved.parent_id, self.finance)
        self.assertFalse(own_sections_under(self.env, host))
        self.assertEqual(core.parent_id, host)
        self.assertEqual(
            self._english_name(self.finance), COMMUNITY_ROOT_MENU_NAME)
