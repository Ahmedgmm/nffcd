# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Browser checks of the credit limit screens on the Owl 3 web client.

Opens the credit policy and override log screens, the partner credit stat
button and the draft invoice credit warning in headless Chrome. Any console
error, uncaught exception or error dialog fails the test.
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
# ``expand`` runs first and is the one tolerant step: it clicks its selector
# when the element is there and moves on when it is not. It exists for
# containers that core collapses once they hold enough children (the stat
# button box files its overflow under a More dropdown), where the awaited
# element is absent from the DOM entirely until the container is opened.
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
                if (step.expand) {
                    const collapsed = document.querySelector(step.expand);
                    if (collapsed) {
                        collapsed.click();
                    }
                }
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


@tagged('eh_account_credit_limit', 'post_install', '-at_install')
@unittest.skipIf(
    websocket is None,
    "websocket-client is required to drive headless Chrome",
)
class TestCreditLimitWebClient(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        admin = cls.env.ref('base.user_admin')
        admin.group_ids |= cls.env.ref('eh_account_base.group_eh_manager')
        cls.company = admin.company_id
        cls.policy = cls.env['eh.credit.policy'].create({
            'name': 'Web client credit policy',
            'company_id': cls.company.id,
            'is_company_default': True,
            'default_credit_limit': 1000.0,
            'enforcement_mode': 'block',
            'include_drafts': False,
        })
        cls.partner = cls.env['res.partner'].create({
            'name': 'Credit web client customer',
        })
        income = cls.env['account.account'].search([
            ('account_type', '=', 'income'),
            ('company_ids', 'in', cls.company.ids),
        ], limit=1)

        def invoice(amount):
            return cls.env['account.move'].with_company(cls.company).create({
                'move_type': 'out_invoice',
                'company_id': cls.company.id,
                'partner_id': cls.partner.id,
                'invoice_date': '2026-04-15',
                'invoice_line_ids': [(0, 0, {
                    'name': 'Credit web client sale',
                    'quantity': 1,
                    'price_unit': amount,
                    'account_id': income.id,
                    'tax_ids': [(5, 0, 0)],
                })],
            })

        invoice(900.0).action_post()
        cls.draft_invoice = invoice(300.0)

    def _check_screen(self, url, steps):
        self.browser_js(
            url,
            _SCREEN_CHECK % json.dumps(steps),
            'odoo.isReady === true',
            login='admin',
            timeout=120,
        )

    def test_policy_list_and_form(self):
        self._check_screen(
            '/odoo/action-eh_account_credit_limit.action_eh_credit_policy',
            [
                {'wait': '.o_list_view .o_data_row', 'click': '.o_data_row .o_data_cell'},
                {'wait': '.o_form_view .o_field_widget[name="default_credit_limit"]'},
            ],
        )

    def test_override_log_list(self):
        self._check_screen(
            '/odoo/action-eh_account_credit_limit.action_eh_credit_override_log',
            [{'wait': '.o_list_view'}],
        )

    def test_partner_credit_stat_button_opens_override_log(self):
        # The stat button box keeps only a handful of buttons inline and
        # renders the rest inside a More dropdown, in an overlay outside
        # .o_form_view. How many sibling modules add a partner stat button
        # therefore decides where ours is drawn, so open that dropdown when
        # it is present and anchor the assertions on the button box itself
        # rather than on the form element that only holds the inline half.
        self._check_screen(
            '/odoo/action-base.action_partner_form/%s' % self.partner.id,
            [
                {'wait': '.o_form_view .o-form-buttonbox'},
                {
                    'expand': '.o_form_view .o-form-buttonbox .o_button_more',
                    'wait': '.o-form-buttonbox'
                            ' button[name="action_view_eh_credit_status"]'
                            ' i.oi[data-icon="credit_card"]',
                    # The button ships an Odoo-icon glyph. The previous
                    # selector named the pre-Owl .oe_button_box wrapper,
                    # a class the form compiler strips, so it matched
                    # nothing; this one is scoped to our own button and
                    # actually fails if a legacy Font Awesome glyph
                    # returns to it.
                    'forbid': 'button[name="action_view_eh_credit_status"]'
                              ' .fa',
                },
                {
                    'wait': 'button[name="action_view_eh_credit_status"]'
                            ' .o_field_widget[name="eh_credit_status"]',
                    'click': 'button[name="action_view_eh_credit_status"]',
                },
                {'wait': '.o_list_view'},
            ],
        )

    def test_draft_invoice_shows_credit_warning_and_override(self):
        self.draft_invoice.invalidate_recordset()
        self.assertTrue(self.draft_invoice.eh_credit_warning)
        self._check_screen(
            '/odoo/action-account.action_move_out_invoice_type/%s'
            % self.draft_invoice.id,
            [
                {'wait': '.alert-warning .o_field_widget[name="eh_credit_warning"]'},
                {'wait': '.o_form_view .o_field_widget[name="eh_credit_override_reason"]'},
            ],
        )
