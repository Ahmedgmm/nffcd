# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Browser checks of the approval screens on the Owl 3 web client.

Every list, kanban and form the module ships is opened in headless Chrome,
together with the approval stat buttons it injects on bills and partners
and the onboarding tour. Any console error, uncaught exception or error
dialog fails the test.
"""

import json
import unittest

from odoo.tests import HttpCase, tagged

from odoo.addons.eh_account_base.tests.common import run_tour_as_onboarding

try:
    # Odoo's headless Chrome driver talks to the browser through it; without
    # it the framework would log a warning per test before skipping.
    import websocket
except ImportError:
    websocket = None

# Waits for every selector in turn, then optionally checks ``forbid`` is
# absent and clicks the awaited element (``click: true``) or another one.
# ``reveal`` names an element to click only when it is there, such as the
# "More" toggle a form button box grows once it holds more stat buttons than
# fit, so the next step finds the button whichever way the box renders.
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
                const reveal = step.reveal && document.querySelector(step.reveal);
                if (reveal) {
                    console.log('revealed ' + step.reveal);
                    reveal.click();
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


@tagged('eh_account_approval', 'post_install', '-at_install')
@unittest.skipIf(
    websocket is None,
    "websocket-client is required to drive headless Chrome",
)
class TestApprovalWebClient(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        admin = cls.env.ref('base.user_admin')
        admin.group_ids |= cls.env.ref('eh_account_base.group_eh_manager')
        cls.admin = admin
        cls.company = admin.company_id
        cls.partner = cls.env['res.partner'].create({
            'name': 'Approval web client vendor',
        })
        expense = cls.env['account.account'].search([
            ('account_type', '=', 'expense'),
            ('company_ids', 'in', cls.company.ids),
        ], limit=1)
        cls.policy = cls.env['eh.approval.policy'].create({
            'name': 'Approval web client policy',
            'company_id': cls.company.id,
            'document_type': 'in_invoice',
            'rule_ids': [(0, 0, {
                'name': 'Every governed bill',
                'min_amount': 0.0,
                'max_amount': 0.0,
                'sla_hours': 4,
                'reminder_after_hours': 1,
                'step_ids': [(0, 0, {
                    'approver_ids': [(6, 0, admin.ids)],
                    'approval_minimum': 1,
                })],
            })],
        })
        cls.bill = cls.env['account.move'].with_company(cls.company).create({
            'move_type': 'in_invoice',
            'company_id': cls.company.id,
            'partner_id': cls.partner.id,
            'invoice_date': '2026-06-01',
            'invoice_line_ids': [(0, 0, {
                'name': 'Approval web client line',
                'quantity': 1,
                'price_unit': 180.0,
                'account_id': expense.id,
                'tax_ids': [(5, 0, 0)],
            })],
        })
        cls.bill.action_eh_request_approval()
        cls.request = cls.bill.eh_active_approval_request_id

    def _check_screen(self, url, steps):
        self.browser_js(
            url,
            _SCREEN_CHECK % json.dumps(steps),
            'odoo.isReady === true',
            login='admin',
            timeout=120,
        )

    def test_request_kanban_and_form(self):
        self.assertEqual(self.request.state, 'in_review')
        self.assertTrue(self.request.due_at)
        self._check_screen(
            '/odoo/action-eh_account_approval.action_eh_approval_request',
            [
                {
                    'wait': '.o_kanban_view .o_kanban_record'
                            ' i.oi[data-icon="schedule"]',
                    'forbid': '.o_kanban_view .fa',
                },
                {'wait': '.o_kanban_record .o_field_widget[name="due_at"]'},
                {
                    'wait': '.o_kanban_record i.oi[data-icon="group"]',
                    'click': '.o_kanban_record',
                },
                {'wait': '.o_form_view .o_form_sheet'},
            ],
        )

    def test_request_list_view(self):
        self._check_screen(
            '/odoo/action-eh_account_approval.action_eh_approval_request'
            '?view_type=list',
            [
                {'wait': '.o_list_view .o_data_row', 'click': '.o_data_row .o_data_cell'},
                {'wait': '.o_form_view .o_form_sheet'},
            ],
        )

    def test_policy_list_and_form(self):
        self._check_screen(
            '/odoo/action-eh_account_approval.action_eh_approval_policy',
            [
                {'wait': '.o_list_view .o_data_row', 'click': '.o_data_row .o_data_cell'},
                {'wait': '.o_form_view .o_form_sheet'},
            ],
        )

    def test_log_list(self):
        self.assertTrue(self.request.log_ids)
        self._check_screen(
            '/odoo/action-eh_account_approval.action_eh_approval_log',
            [{'wait': '.o_list_view .o_data_row'}],
        )

    def test_bill_form_shows_approval_stat_button(self):
        self._check_screen(
            '/odoo/action-account.action_move_in_invoice_type/%s'
            % self.bill.id,
            [
                {
                    'wait': '.o_form_view'
                            ' button[name="action_eh_view_approval_request"]'
                            ' i.oi[data-icon="gavel"]',
                    'click': '.o_form_view'
                             ' button[name="action_eh_view_approval_request"]',
                },
                {'wait': '.o_form_view .o_field_widget[name="move_id"]'},
            ],
        )

    def test_new_bill_form_opens(self):
        self._check_screen(
            '/odoo/action-account.action_move_in_invoice_type/new',
            [{'wait': '.o_form_view .o_field_widget[name="partner_id"]'}],
        )

    def test_partner_form_and_list_show_pending_approvals(self):
        # Every installed app can add a partner stat button; past the few the
        # box shows, the rest move into its "More" dropdown, rendered as a
        # second .o-form-buttonbox in the overlay container.
        self._check_screen(
            '/odoo/action-base.action_partner_form/%s' % self.partner.id,
            [{
                'wait': '.o_form_view .o-form-buttonbox',
                'reveal': '.o_form_view .o-form-buttonbox .o_button_more',
            }, {
                'wait': '.o-form-buttonbox'
                        ' button[name="action_view_eh_pending_approvals"]'
                        ' i.oi[data-icon="hourglass_top"]',
            }],
        )
        self._check_screen(
            '/odoo/action-base.action_partner_form?view_type=list',
            [{
                'wait': '.o_eh_list_statistics'
                        ' i.oi[data-icon="hourglass_top"]',
                'forbid': '.o_eh_list_statistics .fa',
            }],
        )

    def test_setup_tour(self):
        self.start_tour(
            '/odoo/action-eh_account_approval.action_eh_approval_request',
            'eh_approval_setup_tour',
            login='admin',
        )

    def test_setup_tour_on_a_narrow_screen(self):
        """On a narrow desktop the navbar folds its last sections, Configuration
        among them, into the "More" menu; the tour must still reach the
        policy list through it."""
        self.browser_size = '820x900'
        # The navbar hides a folded section with d-none and lists it in More.
        configuration = '[data-menu-xmlid="account.menu_finance_configuration"]'
        self._check_screen(
            '/odoo/action-eh_account_approval.action_eh_approval_request',
            [{
                'wait': '.o_menu_sections_more',
                'forbid': '.o_menu_sections > :not(.d-none)%s, '
                          '.o_menu_sections > :not(.d-none) %s'
                          % (configuration, configuration),
            }],
        )
        self.start_tour(
            '/odoo/action-eh_account_approval.action_eh_approval_request',
            'eh_approval_setup_tour',
            login='admin',
        )

    def test_setup_tour_starts_from_its_database_record(self):
        run_tour_as_onboarding(
            self, 'eh_approval_setup_tour',
            '/odoo/action-eh_account_approval.action_eh_approval_request',
        )
