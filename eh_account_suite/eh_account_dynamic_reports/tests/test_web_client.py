# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Browser checks of the dynamic report viewer on the Owl 3 web client.

Every report client action is opened in headless Chrome and must mount
its table without a console error, an error dialog or a Font Awesome
leftover. One report is then driven through the interactive paths that
use Owl 3 specific wiring (signal refs, props schemas, the popover and
notification plugins, parametric template calls). The module's Hoot unit
suite runs in the same browser.
"""

import json
import unittest

from odoo import fields
from odoo.tests import HttpCase, tagged

from odoo.addons.eh_account_base.tests.common import (
    EhAccountIntegrationTestCase,
)

try:
    # Odoo's headless Chrome driver talks to the browser through it; without
    # it the framework would log a warning per test before skipping.
    import websocket
except ImportError:
    websocket = None

# Waits for every selector in turn, then optionally clicks one element and
# waits for the next screen. A step may also name an optional control to
# click only when it is shown, such as the form button box "More" menu that
# holds the stat buttons past the visible ones. Any console error or uncaught
# exception (an Owl render crash, a missing import, an error dialog) fails the
# test.
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
                for (const selector of step.forbid || []) {
                    if (document.querySelector(selector)) {
                        throw new Error('Unexpected element ' + selector);
                    }
                }
                if (step.click_if_present) {
                    const optional = document.querySelector(
                        step.click_if_present,
                    );
                    if (optional) {
                        optional.click();
                    }
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

# Screens every loaded report must satisfy: the table is mounted, no error
# banner is shown and no Font Awesome class survived the Odoo 20 icon port.
_REPORT_LOADED = {
    'wait': '.eh_dr .eh_dr_table',
    'forbid': ['.eh_dr .alert-danger', '.eh_dr .fa'],
}

REPORT_ACTIONS = (
    'action_open_executive_summary_viewer',
    'action_open_trial_balance_viewer',
    'action_open_profit_and_loss_viewer',
    'action_open_balance_sheet_viewer',
    'action_open_general_ledger_viewer',
    'action_open_partner_ledger_viewer',
    'action_open_aged_receivable_viewer',
    'action_open_aged_payable_viewer',
    'action_open_cash_flow_viewer',
    'action_open_deferred_revenue_viewer',
    'action_open_deferred_expense_viewer',
    'action_open_bank_reconciliation_viewer',
    'action_eh_report_analytic_balance',
)


def _hoot_hash(text):
    """Hoot job id for a test or suite path (same algorithm as web's
    HootCommon._generate_hash)."""
    value = 0
    for char in text:
        value = (value << 5) - value + ord(char)
        value &= 0xFFFFFFFF
    return f'{value:08x}'


@tagged('eh_account_dynamic_reports', 'post_install', '-at_install')
@unittest.skipIf(
    websocket is None,
    "websocket-client is required to drive headless Chrome",
)
class TestDynamicReportWebClient(HttpCase, EhAccountIntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        admin = cls.env.ref('base.user_admin')
        admin.write({'group_ids': [
            (4, cls.env.ref('eh_account_base.group_eh_manager').id),
        ]})
        if 'tour_enabled' in admin._fields:
            admin.tour_enabled = False
        # Nest cash under a parent account so the grouped reports render an
        # unfoldable hierarchy line, and give it a name long enough for the
        # ellipsis cell to clip it.
        cls.cash_parent = cls.env['account.account'].create({
            'name': 'Cash and cash equivalents held at bank and on hand '
                    'for the web client check',
            'code': '10',
            'account_type': 'asset_cash',
            'active': False,
            'company_ids': [(6, 0, cls.company.ids)],
        })
        cls.account_cash.parent_id = cls.cash_parent
        # The viewer opens on the current month, so post inside it.
        cls.post_balanced_move(
            [
                {'account': cls.account_cash, 'debit': 750.0},
                {'account': cls.account_revenue, 'credit': 750.0},
            ],
            date=fields.Date.context_today(cls.env.user),
        )

    def _check_screen(self, url, steps):
        self.browser_js(
            url,
            _SCREEN_CHECK % json.dumps(steps),
            'odoo.isReady === true',
            login='admin',
            timeout=120,
        )

    def test_every_report_action_mounts(self):
        for action in REPORT_ACTIONS:
            with self.subTest(action=action):
                self._check_screen(
                    '/odoo/action-eh_account_dynamic_reports.%s' % action,
                    [_REPORT_LOADED],
                )

    def test_viewer_interactions(self):
        # debug=1 turns on Owl props validation, so a props schema that
        # rejects what the viewer passes fails here.
        self._check_screen(
            '/odoo/action-eh_account_dynamic_reports.'
            'action_open_trial_balance_viewer?debug=1',
            [
                _REPORT_LOADED,
                # Fold the parent-account hierarchy line.
                {
                    'wait': '.eh_dr_unfold_caret[aria-expanded="true"]',
                    'click': True,
                },
                {'wait': '.eh_dr_unfold_caret[aria-expanded="false"]'},
                # Clipped long names open the ellipsis popover.
                {'wait': '.eh_dr_ellipsis_btn', 'click': True},
                # Copy reports through the notification plugin.
                {
                    'wait': '.eh_dr_ellipsis_pop .eh_dr_ellipsis_copy',
                    'click': True,
                },
                {'wait': '.o_notification'},
                # Row notes use a parametric template call.
                {'wait': '.eh_dr_table .eh_dr_note_btn', 'click': True},
                {
                    'wait': '.eh_dr_note_popover .eh_dr_note_textarea',
                    'click': '.eh_dr_note_pop_close',
                },
                # Advanced filters and the light theme.
                {'wait': '.eh_dr_collapse_toggle', 'click': True},
                # "Pick more" lazily loads the core records picker dialog.
                {
                    'wait': '.eh_dr_filters_advanced .eh_dr_more_btn',
                    'click': True,
                },
                {
                    'wait': '.o_dialog .o_list_view',
                    'click': '.o_dialog .btn-close',
                },
                {
                    'wait': '.eh_dr_theme_choice:first-child',
                    'click': True,
                },
                {'wait': '.eh_dr[data-eh-theme="light"] .eh_dr_table'},
                # Refresh re-renders through the body signal ref.
                {
                    'wait': '.eh_dr_actions .btn-secondary:not([disabled])',
                    'click': True,
                },
                _REPORT_LOADED,
            ],
        )

    def test_noncash_register_list_and_form(self):
        self.env['eh.noncash.transaction'].create({
            'name': 'Racking acquired under a lease',
            'amount': 1200.0,
            'kind': 'lease',
        })
        self._check_screen(
            '/odoo/action-eh_account_dynamic_reports.'
            'action_eh_noncash_transaction',
            [
                {
                    'wait': '.o_list_view .o_data_row',
                    'click': '.o_data_row .o_data_cell',
                },
                {'wait': '.o_form_view .o_form_sheet'},
            ],
        )

    def test_partner_statement_buttons_use_odoo20_icons(self):
        partner = self.env['res.partner'].create({
            'name': 'EH statement button partner',
            'customer_rank': 1,
            'supplier_rank': 1,
        })
        self._check_screen(
            '/odoo/res.partner/%s' % partner.id,
            [
                # With many apps installed the statement buttons sit past
                # the visible stat buttons, inside the "More" menu.
                {
                    'wait': '.o_form_view .o-form-buttonbox'
                            ' button.oe_stat_button',
                    'click_if_present': '.o-form-buttonbox .o_button_more',
                },
                {
                    'wait': 'button[name="action_print_customer_statement"]'
                            ' i.oi[data-icon="description"]',
                },
                {
                    'wait': 'button[name="action_print_vendor_statement"]'
                            ' i.oi[data-icon="description"]',
                },
            ],
        )

    def test_hoot_unit_suite(self):
        suite = _hoot_hash('@eh_account_dynamic_reports')
        self.browser_js(
            '/web/tests?headless&loglevel=2&preset=desktop&timeout=15000'
            '&id=%s' % suite,
            '', '',
            login='admin',
            timeout=600,
            success_signal='[HOOT] Test suite succeeded',
            error_checker=lambda message: '[HOOT]' not in message,
        )
