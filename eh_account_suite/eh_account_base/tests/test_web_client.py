# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Browser checks of the module's screens and assets on the Owl 3 client."""

import json
import unittest

from odoo.tests import HttpCase, tagged

try:
    # Odoo's headless Chrome driver talks to the browser through it; without
    # it the framework would log a warning per test before skipping.
    import websocket
except ImportError:
    websocket = None

# Waits for every selector in turn, then optionally clicks one element and
# waits for the next screen. Any console error or uncaught exception (an Owl
# render crash, a missing import, an error dialog) fails the test.
_SCREEN_CHECK = """
    (async () => {
        const steps = %s;
        const waitFor = async (selector) => {
            const deadline = Date.now() + 30000;
            let element = document.querySelector(selector);
            while (!element) {
                if (Date.now() > deadline) {
                    throw new Error('Timed out waiting for ' + selector);
                }
                await new Promise((resolve) => setTimeout(resolve, 100));
                element = document.querySelector(selector);
            }
            return element;
        };
        try {
            for (const step of steps) {
                const element = await waitFor(step.wait);
                if (document.querySelector('.o_error_dialog')) {
                    throw new Error('Error dialog after ' + step.wait);
                }
                if (step.forbid && document.querySelector(step.forbid)) {
                    throw new Error('Unexpected element ' + step.forbid);
                }
                if (step.click) {
                    (step.click === true
                        ? element
                        : await waitFor(step.click)).click();
                }
            }
            console.log('test successful');
        } catch (error) {
            console.error(error.message);
        }
    })();
"""


@tagged('eh_account_base', 'post_install', '-at_install')
@unittest.skipIf(
    websocket is None,
    "websocket-client is required to drive headless Chrome",
)
class TestWebClient(HttpCase):

    def _check_screen(self, url, steps):
        self.browser_js(
            url,
            _SCREEN_CHECK % json.dumps(steps),
            'odoo.isReady === true',
            login='admin',
            timeout=120,
        )

    def test_partner_list_statistics_widget_renders_odoo20_icons(self):
        """The suite widget replaces core contact statistics on the partner
        list: it must mount on Owl 3 and draw Material Symbols icons."""
        partner = self.env['res.partner'].create({
            'name': 'EH statistics widget partner',
        })
        # A customer invoice gives the partner the core accounting statistic
        # (icon ``edit_square``), rendered through the suite widget.
        self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
        })
        self._check_screen(
            '/odoo/action-base.action_partner_form?view_type=list',
            [{
                'wait': '.o_eh_list_statistics .o_eh_list_statistics_badge'
                        ' i.oi[data-icon="edit_square"]',
                'forbid': '.o_eh_list_statistics .fa',
            }],
        )

    def test_report_execution_audit_log_list_and_form(self):
        admin = self.env.ref('base.user_admin')
        self.env['eh.account.report.execution'].with_user(
            admin,
        ).start_execution(
            report_code='web_client_check',
            name='Web client check',
            options={'date': {'date_to': '2026-06-30'}},
            company_ids=admin.company_id.ids,
        )
        self._check_screen(
            '/odoo/action-eh_account_base.action_eh_account_report_execution',
            [
                {'wait': '.o_list_view .o_data_row', 'click': '.o_data_row .o_data_cell'},
                {'wait': '.o_form_view .o_form_readonly, .o_form_view .o_form_sheet'},
            ],
        )

    def test_dynamic_report_registry_list_and_form(self):
        self.env['eh.account.dynamic.report'].create({
            'code': 'web_client_registry_check',
            'name': 'Web client registry check',
            'handler_model': 'eh.account.dynamic.report.handler.sectioned',
        })
        self._check_screen(
            '/odoo/action-eh_account_base.action_eh_account_dynamic_report',
            [
                {'wait': '.o_list_view .o_data_row', 'click': '.o_data_row .o_data_cell'},
                {'wait': '.o_form_view .o_form_sheet'},
            ],
        )

    def test_report_run_wizard_opens_from_definition(self):
        Report = self.env['eh.account.dynamic.report']
        report = Report.search([('code', '=', 'trial_balance')], limit=1)
        if not report:
            report = Report.create({
                'code': 'trial_balance',
                'name': 'Trial Balance',
                'handler_model': 'eh.account.dynamic.report.handler.sectioned',
            })
        # The run wizard opens as a dialog. Only a handler that declares the
        # native parent-account layout (the Trial Balance, P&L and Balance
        # Sheet of the dynamic reports app) offers the hierarchy toggle;
        # Base's own sectioned handler does not, so on Base alone the dialog
        # must open without it.
        toggle = '.modal .o_form_view [name="hierarchical_groups"]'
        if report.supports_account_hierarchy:
            dialog = {'wait': toggle}
        else:
            dialog = {
                'wait': '.modal .o_form_view [name="company_ids"]',
                'forbid': toggle,
            }
        self._check_screen(
            '/odoo/action-eh_account_base.action_eh_account_dynamic_report/%s'
            % report.id,
            [
                {
                    'wait': '.o_form_view button[name="action_open_run_wizard"]',
                    'click': True,
                },
                dialog,
            ],
        )

    def test_settings_block_sits_in_accounting_app(self):
        self._check_screen(
            '/odoo/settings#account',
            [{
                'wait': '.app_settings_block[data-key="account"]'
                        ' #eh_gl_row_limit_setting',
            }],
        )
