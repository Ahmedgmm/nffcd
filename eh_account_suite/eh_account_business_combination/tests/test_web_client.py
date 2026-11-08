# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Browser checks of the business combination and equity method screens on
the Owl 3 web client.

The create path is covered by the eh_business_combination_test_tour; these
checks open a recognised combination with its journal entry stat button and
the associates register. Any console error, uncaught exception or error
dialog fails the test.
"""

import json
import unittest

from odoo.tests import HttpCase, tagged

try:
    # Odoo's headless Chrome driver talks to the browser through it; without
    # it the framework would log a warning per test before skipping.
    import websocket
except ImportError:
    websocket = None

# Waits for every selector in turn, then optionally checks ``forbid`` is
# absent and clicks the awaited element (``click: true``) or another one.
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
            if (document.querySelector('.o_error_dialog')) {
                throw new Error('Error dialog at the end of the check');
            }
            console.log('test successful');
        } catch (error) {
            console.error(error.message);
        }
    })();
"""


@tagged('eh_account_business_combination', 'post_install', '-at_install')
@unittest.skipIf(
    websocket is None,
    "websocket-client is required to drive headless Chrome",
)
class TestBusinessCombinationWebClient(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        admin = cls.env.ref('base.user_admin')
        admin.group_ids |= cls.env.ref('eh_account_base.group_eh_manager')
        cls.company = admin.company_id
        Account = cls.env['account.account']

        def account(code, name, account_type):
            return Account.create({
                'code': code,
                'name': name,
                'account_type': account_type,
                'company_ids': [(6, 0, cls.company.ids)],
            })

        journal = cls.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', cls.company.id),
        ], limit=1)
        # Recognition is reserved to EH accounting managers, so the
        # combination is created and recognised by the admin actor.
        cls.combination = cls.env['eh.business.combination'].with_user(
            admin,
        ).create({
            'name': '/',
            'acquiree_name': 'Web Client Target Ltd',
            'company_id': cls.company.id,
            'consideration_transferred': 1000.0,
            'nci_amount': 0.0,
            'fv_identifiable_net_assets': 700.0,
            'goodwill_account_id': account(
                '1891', 'Web Client Goodwill', 'asset_non_current').id,
            'clearing_account_id': account(
                '1892', 'Web Client Acquisition Clearing', 'asset_current').id,
            'gain_account_id': account(
                '4891', 'Web Client Bargain Purchase Gain', 'income_other').id,
            'journal_id': journal.id,
        })
        cls.combination.action_recognise()

    def _check_screen(self, url, steps):
        self.browser_js(
            url,
            _SCREEN_CHECK % json.dumps(steps),
            'odoo.isReady === true',
            login='admin',
            timeout=120,
        )

    def test_recognised_combination_form_opens_its_entry(self):
        self.assertEqual(self.combination.state, 'recognised')
        self.assertTrue(self.combination.move_id)
        self._check_screen(
            '/odoo/action-eh_account_business_combination'
            '.action_eh_business_combination/%s' % self.combination.id,
            [
                {
                    'wait': '.o_form_view button[name="action_view_move"]'
                            ' i.oi[data-icon="book"]',
                    'forbid': '.o_form_view .oe_button_box .fa',
                    'click': '.o_form_view button[name="action_view_move"]',
                },
                {'wait': '.o_form_view .o_field_widget[name="line_ids"]'},
            ],
        )

    def test_combination_list(self):
        self._check_screen(
            '/odoo/action-eh_account_business_combination'
            '.action_eh_business_combination',
            [{'wait': '.o_list_view .o_data_row'}],
        )

    def test_equity_investment_list_and_new_form(self):
        self._check_screen(
            '/odoo/action-eh_account_business_combination'
            '.action_eh_equity_investment',
            [
                {'wait': '.o_list_view', 'click': '.o_list_button_add'},
                {'wait': '.o_form_view .o_form_sheet'},
            ],
        )
