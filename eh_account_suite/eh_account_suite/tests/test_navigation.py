"""Accounting navigation keeps workflows reachable across roles and updates."""

import ast
from copy import deepcopy
from io import BytesIO
from pathlib import Path

from lxml import etree

from odoo.tests import new_test_user, tagged
from odoo.tools.convert import convert_xml_import

from odoo.addons.base.tests.common import BaseCommon
from odoo.addons.eh_account_suite.navigation import refresh_suite_navigation
from odoo.addons.eh_account_suite.tests.common import (
    accounting_app,
    is_enterprise_layout,
    own_sections_under,
)


@tagged('eh_account_suite', 'post_install', '-at_install')
class TestAccountingNavigation(BaseCommon):
    _test_user_groups = ()

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.repo_root = Path(__file__).resolve().parents[2]
        cls.menu_sources = []
        cls.menu_xmlids = set()
        manifests = {}

        def visit(module):
            manifest_path = cls.repo_root / module / '__manifest__.py'
            if module in manifests or not manifest_path.exists():
                return
            manifest = ast.literal_eval(manifest_path.read_text())
            manifests[module] = manifest
            for dependency in manifest.get('depends', []):
                visit(dependency)
            for filename in manifest.get('data', []):
                if not filename.endswith('.xml'):
                    continue
                document = etree.parse(str(cls.repo_root / module / filename))
                nodes = document.findall('.//menuitem')
                if not nodes:
                    continue
                cls.menu_sources.append((module, filename, nodes))
                for node in nodes:
                    xmlid = node.get('id')
                    cls.menu_xmlids.add(
                        xmlid if '.' in xmlid else '%s.%s' % (module, xmlid)
                    )

        visit('eh_account_suite')
        cls.roles = {
            name: new_test_user(
                cls.env,
                login='eh_navigation_%s' % name,
                groups='base.group_user,%s' % group,
                company_id=cls.env.company.id,
            )
            for name, group in (
                ('operator', 'eh_account_base.group_eh_user'),
                ('manager', 'eh_account_base.group_eh_manager'),
                ('auditor', 'eh_account_base.group_eh_auditor'),
                ('grant_reviewer', 'eh_account_grants.group_eh_grant_reviewer'),
                ('anomaly_reviewer', 'eh_account_ai_agent.group_eh_ai_reviewer'),
            )
        }
        cls.roles['employee'] = new_test_user(
            cls.env, login='eh_navigation_employee', groups='base.group_user',
        )

    def _assert_reachable(self, role, xmlid):
        """A leaf is useful only when every ancestor reaches the app switcher."""
        menu = self.env.ref(xmlid)
        visible_ids = self.env['ir.ui.menu'].with_user(
            self.roles[role],
        )._visible_menu_ids()
        while menu:
            self.assertIn(menu.id, visible_ids, '%s: %s' % (role, menu.complete_name))
            menu = menu.parent_id

    def _assert_hidden(self, role, xmlid):
        visible_ids = self.env['ir.ui.menu'].with_user(
            self.roles[role],
        )._visible_menu_ids()
        self.assertNotIn(self.env.ref(xmlid).id, visible_ids, '%s: %s' % (role, xmlid))

    def test_all_suite_menus_share_one_finance_app(self):
        """Every suite menu hangs off the one Accounting app: the finance root
        on Community, the accountant app once Enterprise owns Accounting."""
        app = accounting_app(self.env)
        for xmlid in sorted(self.menu_xmlids):
            menu = self.env.ref(xmlid)
            visited = set()
            while menu.parent_id:
                self.assertNotIn(menu.id, visited, xmlid)
                visited.add(menu.id)
                menu = menu.parent_id
            self.assertEqual(menu, app, xmlid)
        if is_enterprise_layout(self.env):
            self.assertFalse(own_sections_under(
                self.env, self.env.ref('account.menu_finance')))

    def test_web_client_offers_one_accounting_app(self):
        """What each role sees in the app switcher: one Accounting app, and
        every suite entry it may open lives inside that app."""
        app = accounting_app(self.env)
        finance = self.env.ref('account.menu_finance')
        suite_ids = {self.env.ref(xmlid).id for xmlid in self.menu_xmlids}
        roles = dict(self.roles, admin=self.env.ref('base.user_admin'))
        for role, user in roles.items():
            menus = self.env['ir.ui.menu'].with_user(user).with_context(
                lang='en_US').load_menus(False)
            roots = menus['root']['children']
            named_accounting = [
                menu_id for menu_id in roots
                if menus[menu_id]['name'] == 'Accounting'
            ]
            reachable = suite_ids.intersection(menus) - {app.id}
            if not reachable:
                continue
            self.assertEqual(named_accounting, [app.id], role)
            for menu_id in reachable:
                self.assertEqual(
                    menus[menu_id]['app_id'], app.id,
                    '%s: %s' % (role, menus[menu_id]['xmlid']),
                )
            if app != finance:
                self.assertNotIn(finance.id, roots, role)

    def test_daily_work_uses_familiar_sections(self):
        routes = {
            'eh_account_base.menu_eh_operations': accounting_app(self.env),
            'eh_account_setup.menu_setup_guide': 'account.menu_finance_entries',
            'eh_account_assets_pro.menu_eh_assets_root': 'account.menu_finance_entries',
            'eh_account_close_workflow.menu_eh_close_run': 'account.account_closing_menu',
            'eh_account_year_end.menu_eh_year_end_run': 'account.account_closing_menu',
            'eh_account_audit_pack.menu_eh_audit_pack': 'account.account_audit_menu',
            'eh_account_approval.menu_eh_approval_request': 'account.account_audit_control_menu',
            'eh_account_base.menu_eh_config_audit': 'account.account_audit_menu',
            'eh_account_einvoice_peppol.menu_eh_peppol_root': 'account.menu_finance_payables',
            'eh_account_dynamic_reports.menu_balance_sheet': 'account.account_reports_legal_statements_menu',
            'eh_account_statements.menu_eh_soci': 'account.account_reports_legal_statements_menu',
            'eh_account_dynamic_reports.menu_aged_receivable': 'account.account_reports_partners_reports_menu',
            'eh_account_budget_pro.menu_eh_budget_analysis': 'account.account_reports_management_menu',
        }
        if self.env.ref('eh_account_l10n_au_bas.menu_eh_bas_run', raise_if_not_found=False):
            routes['eh_account_l10n_au_bas.menu_eh_bas_run'] = (
                'account.account_reports_taxes_and_fiscal_menu'
            )
        for menu_xmlid, parent in routes.items():
            if isinstance(parent, str):
                parent = self.env.ref(parent)
            self.assertEqual(
                self.env.ref(menu_xmlid).parent_id, parent, menu_xmlid,
            )

    def test_configuration_has_no_branding_only_level(self):
        configuration = self.env.ref('account.menu_finance_configuration')
        for name in (
            'general', 'reports', 'operations', 'assets', 'banking',
            'payments', 'pdc', 'localization',
        ):
            menu = self.env.ref('eh_account_base.menu_eh_config_%s' % name)
            self.assertEqual(menu.parent_id, configuration, name)

    def test_moved_entries_keep_their_original_actions(self):
        actions = {
            'eh_account_setup.menu_setup_guide': 'eh_account_setup.action_setup_guide',
            'eh_account_bank_statement_import.menu_eh_bsi_import_wizard': 'eh_account_bank_statement_import.action_eh_bsi_wizard',
            'eh_account_batch_payment.menu_eh_batch_payment_root': 'eh_account_batch_payment.action_eh_batch_payment',
            'eh_account_close_workflow.menu_eh_close_run': 'eh_account_close_workflow.action_eh_close_run',
            'eh_account_year_end.menu_eh_year_end_run': 'eh_account_year_end.action_eh_year_end_run',
            'eh_account_approval.menu_eh_approval_request': 'eh_account_approval.action_eh_approval_request',
            'eh_account_audit_pack.menu_eh_audit_pack': 'eh_account_audit_pack.action_eh_audit_pack',
            'eh_account_dynamic_reports.menu_balance_sheet': 'eh_account_dynamic_reports.action_open_balance_sheet_viewer',
            'eh_account_dynamic_reports_pro.menu_eh_report_builder': 'eh_account_dynamic_reports_pro.action_eh_report_builder',
            'eh_account_ecl.menu_eh_ecl_run': 'eh_account_ecl.action_eh_ecl_run',
            'eh_account_grants.menu_eh_gov_grant': 'eh_account_grants.action_eh_gov_grant',
            'eh_account_base.menu_eh_audit_report_execution': 'eh_account_base.action_eh_account_report_execution',
        }
        for menu_xmlid, action_xmlid in actions.items():
            self.assertEqual(
                self.env.ref(menu_xmlid).action, self.env.ref(action_xmlid), menu_xmlid,
            )

    def test_operator_reaches_work_without_manager_configuration(self):
        for xmlid in (
            'eh_account_setup.menu_setup_guide',
            'eh_account_bank_statement_import.menu_eh_bsi_import_wizard',
            'eh_account_reconcile_pro.menu_eh_reconcile_workspace',
            'eh_account_batch_payment.menu_eh_batch_payment_root',
            'eh_account_close_workflow.menu_eh_close_run',
            'eh_account_dynamic_reports.menu_balance_sheet',
            'eh_account_ecl.menu_eh_ecl_run',
        ):
            self._assert_reachable('operator', xmlid)
        for xmlid in (
            'account.menu_finance_configuration',
            'eh_account_dynamic_reports_pro.menu_eh_report_builder',
            'eh_account_sepa_dd.menu_eh_sepa_dd_export',
            'eh_account_approval.menu_eh_approval_log',
        ):
            self._assert_hidden('operator', xmlid)

    def test_auditor_reaches_evidence_without_write_privileges(self):
        for xmlid in (
            'eh_account_base.menu_eh_audit_report_execution',
            'eh_account_approval.menu_eh_approval_log',
            'eh_account_credit_limit.menu_eh_credit_override_log',
            'eh_account_assets_pro.menu_eh_asset_all',
            'eh_account_sepa_ct.menu_eh_sepa_export',
            'eh_account_sepa_dd.menu_eh_sepa_dd_export',
            'eh_account_disclosures.menu_eh_fin_credit_note',
        ):
            self._assert_reachable('auditor', xmlid)
        self._assert_hidden('auditor', 'account.menu_finance_configuration')
        auditor = self.roles['auditor']
        for model_name in ('eh.account.report.execution', 'eh.asset', 'eh.sepa.dd.export'):
            model = self.env[model_name].with_user(auditor)
            self.assertTrue(model.has_access('read'), model_name)
            for operation in ('create', 'write', 'unlink'):
                self.assertFalse(model.has_access(operation), '%s: %s' % (model_name, operation))

    def test_narrow_reviewer_reaches_grants_only(self):
        self._assert_reachable('grant_reviewer', 'eh_account_grants.menu_eh_gov_grant')
        self._assert_hidden('grant_reviewer', 'eh_account_revenue.menu_eh_revenue_contract')
        self._assert_hidden('grant_reviewer', 'eh_account_base.menu_eh_operations')
        self._assert_hidden('employee', 'account.menu_finance')

    def test_anomaly_reviewer_has_one_working_shortcut(self):
        self._assert_reachable(
            'anomaly_reviewer', 'eh_account_ai_agent.menu_eh_account_anomaly_finding',
        )
        self._assert_hidden(
            'anomaly_reviewer', 'eh_account_ai_agent.menu_eh_account_anomaly_review',
        )
        original = self.env.ref('eh_account_ai_agent.menu_eh_account_anomaly_review')
        self.assertEqual(
            original.action,
            self.env.ref('eh_account_ai_agent.action_eh_account_anomaly_finding'),
        )

    def test_manager_reaches_configuration(self):
        for xmlid in (
            'eh_account_dynamic_reports_pro.menu_eh_report_builder',
            'eh_account_bank_statement_import.menu_eh_bsi_profile',
            'eh_account_approval.menu_eh_approval_policy',
            'eh_account_assets_pro.menu_eh_asset_category',
        ):
            self._assert_reachable('manager', xmlid)

    def test_suite_only_upgrade_refreshes_old_dependency_navigation(self):
        close_run = self.env.ref('eh_account_close_workflow.menu_eh_close_run')
        import_menu = self.env.ref('eh_account_bank_statement_import.menu_eh_bsi_import_wizard')
        bank_folder = self.env.ref('eh_account_base.menu_eh_bank_statements')
        original_actions = (close_run.action, import_menu.action)
        close_run.parent_id = self.env.ref('eh_account_base.menu_eh_period_work')
        import_menu.parent_id = self.env.ref('eh_account_base.menu_eh_operations')
        # The new shared folder does not exist before the first suite update.
        # Import menus have been moved out, so this removes no action or data.
        bank_folder.child_id.parent_id = self.env.ref('eh_account_base.menu_eh_operations')
        bank_folder.unlink()

        self.assertGreater(refresh_suite_navigation(self.env), 0)
        self.assertEqual(close_run.parent_id, self.env.ref('account.account_closing_menu'))
        self.assertEqual(
            import_menu.parent_id,
            self.env.ref('eh_account_base.menu_eh_bank_statements'),
        )
        self.assertEqual((close_run.action, import_menu.action), original_actions)
        # The replay files Banking under account.menu_finance, as its XML
        # says; it must still end in the one Accounting app.
        self.assertEqual(
            self.env.ref('eh_account_base.menu_eh_operations').parent_id,
            accounting_app(self.env),
        )
        self.assertGreater(refresh_suite_navigation(self.env), 0)
        self._assert_reachable('auditor', 'eh_account_base.menu_eh_audit_report_execution')

    def test_individual_module_menu_updates_preserve_navigation(self):
        """Replaying each owner's data cannot undo another module's routing.

        Import menu nodes in update mode, with all actions already installed,
        to exercise Odoo's real XML loader without rerunning business data or
        committing a module upgrade inside the transaction test. A real
        update then ends with the registry load hook that keeps the suite
        sections in the Enterprise Accounting app, so each replay is followed
        by that same step. It changes nothing on a Community layout.
        """
        def snapshot():
            return {
                xmlid: (
                    menu.id, menu.parent_id.id, menu.sequence, menu.active,
                    menu.action._name if menu.action else False,
                    menu.action.id if menu.action else False,
                    frozenset(menu.group_ids.ids),
                )
                for xmlid in self.menu_xmlids
                for menu in [self.env.ref(xmlid)]
            }

        expected = snapshot()
        for module, filename, nodes in reversed(self.menu_sources):
            document = etree.Element('odoo')
            for node in nodes:
                document.append(deepcopy(node))
            menu_file = BytesIO(etree.tostring(document))
            menu_file.name = '%s/%s' % (module, filename)
            convert_xml_import(
                self.env(su=True), module, menu_file, mode='update',
            )
            self.env['ir.ui.menu']._eh_sync_finance_app()
            self.assertEqual(snapshot(), expected, '%s/%s' % (module, filename))
