# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Browser checks of the financial dashboard on the Owl 3 web client.

The dashboard client action, its KPI tiles and sparklines declare typed
props, which Owl validates in debug mode, and render Material Symbols
through the "oi" icon font now that Font Awesome is gone. The board is
driven through the paths that exercise that wiring: tiles with prior
period deltas, the custom period form, a drill-down into the records
behind the attention rail, and the legacy form view. The module's Hoot
unit suite runs in the same browser. Any console error fails a test.
"""

import json
import unittest
from datetime import timedelta

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

# Each step waits for a selector (and optionally for a text inside the
# matching elements), checks forbidden selectors, then optionally types
# into an input, picks a select option or clicks.
_SCREEN_CHECK = """
    (async () => {
        const steps = %s;
        const find = (step) => {
            const nodes = [...document.querySelectorAll(step.wait)];
            if (!step.text) {
                return nodes[0];
            }
            return nodes.find((node) => node.textContent.includes(step.text));
        };
        const waitFor = async (step) => {
            const deadline = Date.now() + 30000;
            let element = find(step);
            while (!element) {
                if (Date.now() > deadline) {
                    throw new Error(
                        'Timed out waiting for ' + step.wait
                        + (step.text ? ' with ' + step.text : '')
                    );
                }
                await new Promise((resolve) => setTimeout(resolve, 100));
                element = find(step);
            }
            return element;
        };
        try {
            for (const step of steps) {
                const element = await waitFor(step);
                if (document.querySelector('.o_error_dialog')) {
                    throw new Error('Error dialog after ' + step.wait);
                }
                for (const selector of step.forbid || []) {
                    if (document.querySelector(selector)) {
                        throw new Error('Unexpected element ' + selector);
                    }
                }
                if (step.input !== undefined) {
                    element.value = String(step.input);
                    element.dispatchEvent(new Event('input', { bubbles: true }));
                }
                if (step.select !== undefined) {
                    element.value = String(step.select);
                    element.dispatchEvent(new Event('change', { bubbles: true }));
                }
                if (step.click) {
                    element.click();
                }
            }
            console.log('test successful');
        } catch (error) {
            console.error(error.message);
        }
    })();
"""

_BOARD = "[data-testid='eh-financial-dashboard']"
_NO_LEGACY_ICONS = ['.fa', '.eh_dashboard_inline_error']


def _hoot_hash(text):
    """Hoot job id for a test or suite path (same algorithm as web's
    HootCommon._generate_hash)."""
    value = 0
    for char in text:
        value = (value << 5) - value + ord(char)
        value &= 0xFFFFFFFF
    return f'{value:08x}'


@tagged('eh_account_dashboard', 'post_install', '-at_install')
@unittest.skipIf(
    websocket is None,
    "websocket-client is required to drive headless Chrome",
)
class TestDashboardWebClient(HttpCase, EhAccountIntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        admin = cls.env.ref('base.user_admin')
        admin.write({'group_ids': [
            (4, cls.env.ref('eh_account_base.group_eh_manager').id),
        ]})
        if 'tour_enabled' in admin._fields:
            admin.tour_enabled = False
        today = fields.Date.context_today(cls.env.user)
        # Activity in this period and in the prior one gives every
        # comparison tile a delta badge, and a posted customer invoice
        # that is past due fills the attention rail.
        for date, amount in (
            (today, 900.0),
            (today - timedelta(days=40), 400.0),
        ):
            cls.post_balanced_move(
                [
                    {'account': cls.account_cash, 'debit': amount},
                    {'account': cls.account_revenue, 'credit': amount},
                ],
                date=date,
            )
        cls.late_invoice = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': cls.partner_a.id,
            'invoice_date': today - timedelta(days=45),
            'invoice_date_due': today - timedelta(days=15),
            'invoice_line_ids': [(0, 0, {
                'name': 'Late line',
                'account_id': cls.account_revenue.id,
                'quantity': 1.0,
                'price_unit': 250.0,
                'tax_ids': [(6, 0, [])],
            })],
        })
        cls.late_invoice.action_post()
        cls.today = today

    def _check_screen(self, url, steps):
        self.browser_js(
            url,
            _SCREEN_CHECK % json.dumps(steps),
            'odoo.isReady === true',
            login='admin',
            timeout=120,
        )

    def test_board_renders_tiles_icons_and_custom_period(self):
        date_from = (self.today - timedelta(days=60)).isoformat()
        date_to = self.today.isoformat()
        # debug=1 turns on Owl props validation for every tile.
        self._check_screen(
            '/odoo/action-eh_account_dashboard.action_eh_account_dashboard'
            '?debug=1',
            [
                {
                    'wait': _BOARD + ' .eh_dashboard_body',
                    'forbid': _NO_LEGACY_ICONS,
                },
                {'wait': '.eh_dash_kpi i.oi[data-icon="account_balance"]'},
                {'wait': '.eh_dash_kpi i.oi[data-icon="show_chart"]'},
                {'wait': '.eh_dash_delta_badge i.oi[data-icon]'},
                {'wait': '.eh_dash_attn_row i.oi[data-icon="error"]'},
                {'wait': '.eh_dash_spark'},
                {
                    'wait': "[data-testid='eh-dashboard-period']",
                    'select': 'custom',
                },
                {
                    'wait': '.eh_dashboard_custom_period input',
                    'input': date_from,
                },
                {
                    'wait': '.eh_dashboard_custom_period label:last-of-type'
                            ' input',
                    'input': date_to,
                },
                {
                    'wait': '.eh_dashboard_custom_period button',
                    'click': True,
                },
                {
                    'wait': '.eh_dashboard_company',
                    'text': date_from,
                    'forbid': _NO_LEGACY_ICONS,
                },
                {
                    'wait': "[data-testid='eh-dashboard-refresh']"
                            " i.oi[data-icon='refresh']",
                    'click': True,
                },
                {
                    'wait': _BOARD + ' .eh_dashboard_body',
                    'forbid': _NO_LEGACY_ICONS,
                },
            ],
        )
        dashboard = self.env['eh.account.dashboard'].search([
            ('user_id', '=', self.env.ref('base.user_admin').id),
        ])
        self.assertEqual(dashboard.period_mode, 'custom')
        self.assertEqual(
            fields.Date.to_string(dashboard.period_date_from), date_from,
        )

    def test_attention_rail_opens_late_invoices(self):
        self._check_screen(
            '/odoo/action-eh_account_dashboard.action_eh_account_dashboard'
            '?debug=1',
            [
                {'wait': _BOARD + ' .eh_dashboard_body'},
                {
                    'wait': '.eh_dash_attn_row.is-clickable',
                    'text': 'Overdue customer invoices',
                    'click': True,
                },
                {
                    'wait': '.o_list_view .o_data_row',
                    'text': self.late_invoice.name,
                },
            ],
        )

    def test_kpi_tile_drilldown_opens_journal_items(self):
        self._check_screen(
            '/odoo/action-eh_account_dashboard.action_eh_account_dashboard'
            '?debug=1',
            [
                {'wait': _BOARD + ' .eh_dashboard_body'},
                {
                    'wait': '.eh_dash_kpi .eh_dash_kpi_drill',
                    'text': 'View cash entries',
                    'click': True,
                },
                {'wait': '.o_list_view .o_data_row'},
            ],
        )

    def test_legacy_form_view_uses_material_icons(self):
        dashboard = self.env['eh.account.dashboard'].with_user(
            self.env.ref('base.user_admin'),
        ).create({
            'name': 'Form view dashboard',
            'company_id': self.company.id,
        })
        self._check_screen(
            '/odoo/eh.account.dashboard/%s' % dashboard.id,
            [
                {
                    'wait': '.o_form_view .o_form_sheet'
                            ' i.oi[data-icon="payments"]',
                    'forbid': ['.o_form_view .fa'],
                },
                {'wait': 'button[name="action_refresh"] i.oi'},
            ],
        )

    def test_company_form_ratio_thresholds_tab(self):
        self._check_screen(
            '/odoo/res.company/%s' % self.company.id,
            [
                {
                    'wait': '.o_form_view .o_notebook'
                            ' button.nav-link[name="eh_ratio_thresholds"]',
                    'click': True,
                },
                {
                    'wait': '.o_form_view'
                            ' .o_field_widget[name="eh_ratio_warn_ccc_days"]',
                },
            ],
        )

    def test_hoot_unit_suite(self):
        suite = _hoot_hash('@eh_account_dashboard')
        self.browser_js(
            '/web/tests?headless&loglevel=2&preset=desktop&timeout=15000'
            '&id=%s' % suite,
            '', '',
            login='admin',
            timeout=600,
            success_signal='[HOOT] Test suite succeeded',
            error_checker=lambda message: '[HOOT]' not in message,
        )
