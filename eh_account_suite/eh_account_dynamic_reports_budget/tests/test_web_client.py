# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Browser checks of the P&L budget picker on the Owl 3 web client.

The picker is a patch of the dynamic report viewer and an inherited
template, so it only proves itself in a real browser: the P&L viewer must
mount with the three budget selects, choosing a budget must add the
Budget, Budget Var and Budget Var % columns, and the module's Hoot unit
suite must pass. Any console error fails the test.
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

# Each step waits for a selector (and optionally for a text inside the
# matching elements), then optionally picks a select option or clicks.
# Any console error or uncaught exception fails the test.
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

_REPORT_LOADED = {
    'wait': '.eh_dr .eh_dr_table',
    'forbid': ['.eh_dr .alert-danger', '.eh_dr .fa'],
}


def _hoot_hash(text):
    """Hoot job id for a test or suite path (same algorithm as web's
    HootCommon._generate_hash)."""
    value = 0
    for char in text:
        value = (value << 5) - value + ord(char)
        value &= 0xFFFFFFFF
    return f'{value:08x}'


@tagged('eh_account_dynamic_reports_budget', 'post_install', '-at_install')
@unittest.skipIf(
    websocket is None,
    "websocket-client is required to drive headless Chrome",
)
class TestBudgetFilterWebClient(HttpCase, EhAccountIntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        admin = cls.env.ref('base.user_admin')
        admin.write({'group_ids': [
            (4, cls.env.ref('eh_account_base.group_eh_manager').id),
        ]})
        if 'tour_enabled' in admin._fields:
            admin.tour_enabled = False
        # The viewer opens on the current month, so budget and post inside
        # the current year.
        today = fields.Date.context_today(cls.env.user)
        year_start = today.replace(month=1, day=1)
        year_end = today.replace(month=12, day=31)
        cls.budget = cls.env['eh.budget.budget'].create({
            'code': 'web_pl_budget',
            'name': 'Web client P&L budget',
            'company_id': cls.company.id,
            'date_from': year_start,
            'date_to': year_end,
            'line_ids': [(0, 0, {
                'account_id': cls.account_revenue.id,
                'period_from': year_start,
                'period_to': year_end,
                'budgeted_amount': 1200.0,
            })],
        })
        cls.post_balanced_move(
            [
                {'account': cls.account_cash, 'debit': 750.0},
                {'account': cls.account_revenue, 'credit': 750.0},
            ],
            date=today,
        )

    def test_budget_picker_adds_budget_columns(self):
        # debug=1 turns on Owl props validation.
        steps = [
            _REPORT_LOADED,
            {
                'wait': '.eh_dr_filters .eh_dr_filter select option',
                'text': self.budget.name,
            },
            {
                'wait': '.eh_dr_filters .eh_dr_filter select',
                'text': self.budget.name,
                'select': self.budget.id,
            },
            {'wait': '.eh_dr_table thead th', 'text': 'Budget Var %'},
            {'wait': '.eh_dr_filters .eh_dr_filter span',
             'text': 'Budget allocation'},
            _REPORT_LOADED,
        ]
        self.browser_js(
            '/odoo/action-eh_account_dynamic_reports.'
            'action_open_profit_and_loss_viewer?debug=1',
            _SCREEN_CHECK % json.dumps(steps),
            'odoo.isReady === true',
            login='admin',
            timeout=120,
        )

    def test_hoot_unit_suite(self):
        suite = _hoot_hash('@eh_account_dynamic_reports_budget')
        self.browser_js(
            '/web/tests?headless&loglevel=2&preset=desktop&timeout=15000'
            '&id=%s' % suite,
            '', '',
            login='admin',
            timeout=600,
            success_signal='[HOOT] Test suite succeeded',
            error_checker=lambda message: '[HOOT]' not in message,
        )
