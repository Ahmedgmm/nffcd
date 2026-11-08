# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Browser checks of the reconciliation workspace and screens on the Owl 3
web client.

The workspace is a client action written in Owl; these tests mount it in
headless Chrome, drive a real match through it and open every list, kanban
and form the module ships. Any console error, uncaught exception or error
dialog fails the test.
"""

import json
import unittest

from odoo import fields
from odoo.tests import HttpCase, tagged

from odoo.addons.eh_account_base.tests.common import run_tour_as_onboarding

try:
    # Odoo's headless Chrome driver talks to the browser through it; without
    # it the framework would log a warning per test before skipping.
    import websocket
except ImportError:
    websocket = None

# Runs the steps in order. Each step waits for its ``wait`` selector, then
# optionally checks ``forbid`` is absent, picks ``select`` as the value of the
# awaited <select>, clicks it (``click: true``) or another selector, and waits
# for ``gone`` to disappear.
_SCREEN_CHECK = """
    (async () => {
        const steps = %s;
        const deadlineFor = () => Date.now() + 30000;
        const waitFor = async (selector) => {
            const deadline = deadlineFor();
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
        const waitGone = async (selector) => {
            const deadline = deadlineFor();
            while (document.querySelector(selector)) {
                if (Date.now() > deadline) {
                    throw new Error('Still present: ' + selector);
                }
                await new Promise((resolve) => setTimeout(resolve, 100));
            }
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
                if (step.select !== undefined) {
                    element.value = String(step.select);
                    element.dispatchEvent(new Event('change', { bubbles: true }));
                }
                if (step.click) {
                    (step.click === true
                        ? element
                        : await waitFor(step.click)).click();
                }
                if (step.gone) {
                    await waitGone(step.gone);
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


@tagged('eh_account_reconcile_pro', 'post_install', '-at_install')
@unittest.skipIf(
    websocket is None,
    "websocket-client is required to drive headless Chrome",
)
class TestReconcileWebClient(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        admin = cls.env.ref('base.user_admin')
        admin.group_ids |= cls.env.ref('eh_account_base.group_eh_manager')
        cls.admin = admin
        cls.company = admin.company_id
        # Give the tour its own first journal so demonstration statements
        # cannot remain after the one test statement has been matched.
        cls.journal = cls.env['account.journal'].create({
            'name': 'Web Client Bank', 'code': 'WCBK', 'type': 'bank',
            'company_id': cls.company.id, 'sequence': -1000,
        })
        # Matching carries the statement's suspense balance onto the
        # candidate's account and clears it against the original suspense
        # line, which the module only does on a reconcilable suspense
        # account (see test_suspense_config_immutable).
        suspense = cls.journal.suspense_account_id
        if suspense and not suspense.reconcile:
            suspense.reconcile = True
        cls.partner = cls.env['res.partner'].create({
            'name': 'Workspace web client customer',
        })
        Account = cls.env['account.account']
        receivable = Account.search([
            ('account_type', '=', 'asset_receivable'),
            ('company_ids', 'in', cls.company.ids),
        ], limit=1)
        income = Account.search([
            ('account_type', '=', 'income'),
            ('company_ids', 'in', cls.company.ids),
        ], limit=1)
        misc = cls.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', cls.company.id),
        ], limit=1)
        today = fields.Date.today()
        entry = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': misc.id,
            'date': today,
            'ref': 'EHWEB-INV-0001',
            'line_ids': [
                (0, 0, {
                    'account_id': receivable.id,
                    'partner_id': cls.partner.id,
                    'name': 'EHWEB-INV-0001',
                    'debit': 250.0,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'account_id': income.id,
                    'partner_id': cls.partner.id,
                    'name': 'EHWEB-INV-0001',
                    'debit': 0.0,
                    'credit': 250.0,
                }),
            ],
        })
        entry.action_post()
        cls.receivable_line = entry.line_ids.filtered(
            lambda line: line.account_id == receivable,
        )
        cls.statement_line = cls.env['account.bank.statement.line'].create({
            'journal_id': cls.journal.id,
            'date': today,
            'amount': 250.0,
            'partner_id': cls.partner.id,
            'payment_ref': 'EHWEB-INV-0001 payment',
        })

    def _check_screen(self, url, steps):
        self.browser_js(
            url,
            _SCREEN_CHECK % json.dumps(steps),
            'odoo.isReady === true',
            login='admin',
            timeout=120,
        )

    def test_onboarding_tour_walks_the_workspace(self):
        self.start_tour(
            '/odoo/action-eh_account_reconcile_pro.action_eh_reconcile_workspace',
            'eh_reconcile_setup_tour',
            login='admin',
        )

    def test_onboarding_tour_starts_from_its_database_record(self):
        run_tour_as_onboarding(
            self, 'eh_reconcile_setup_tour',
            '/odoo/action-eh_account_reconcile_pro.action_eh_reconcile_workspace',
        )

    def test_workspace_accepts_a_suggested_match(self):
        """Pick the journal, open the statement line and accept the top
        suggestion: the line reconciles and drops out of the open list."""
        self.assertFalse(self.statement_line.is_reconciled)
        self._check_screen(
            '/odoo/action-eh_account_reconcile_pro.action_eh_reconcile_workspace',
            [
                {'wait': '.eh_rec_select', 'select': self.journal.id},
                {'wait': '.eh_rec_statement_search input'},
                {'wait': '.eh_rec_sl', 'click': True},
                {
                    'wait': '.eh_rec_sel_card',
                    'forbid': '.eh_rec_error',
                },
                {'wait': '.eh_rec_candidate_search input'},
                {
                    'wait': '.eh_rec_sug .eh_rec_btn_match',
                    'click': True,
                    'gone': '.eh_rec_sl',
                },
                {'wait': '.o_notification'},
            ],
        )
        self.statement_line.invalidate_recordset()
        self.receivable_line.invalidate_recordset()
        self.assertTrue(self.statement_line.is_reconciled)
        self.assertTrue(self.receivable_line.reconciled)
        audit = self.env['eh.reconciliation.audit'].search([
            ('statement_line_id', '=', self.statement_line.id),
        ])
        self.assertTrue(audit)

    def test_session_kanban_list_and_form(self):
        self.env['eh.reconciliation.session'].with_user(
            self.admin,
        ).open_or_create(self.journal.id)
        self._check_screen(
            '/odoo/action-eh_account_reconcile_pro.action_eh_reconciliation_session',
            [
                {
                    'wait': '.o_kanban_view .o_kanban_record i.oi[data-icon="schedule"]',
                    'forbid': '.o_kanban_view .fa',
                    'click': '.o_kanban_view .o_kanban_record',
                },
                {
                    'wait': '.o_form_view button[name="action_view_audits"]'
                            ' i.oi[data-icon="format_list_bulleted"]',
                },
            ],
        )

    def test_rule_and_audit_screens(self):
        self._check_screen(
            '/odoo/action-eh_account_reconcile_pro.action_eh_reconciliation_rule',
            [
                {'wait': '.o_list_view', 'click': '.o_list_button_add'},
                {'wait': '.o_form_view .o_form_sheet'},
            ],
        )
        self._check_screen(
            '/odoo/action-eh_account_reconcile_pro.action_eh_reconciliation_audit',
            [{'wait': '.o_list_view'}],
        )

    def test_exception_report_wizard_opens(self):
        self._check_screen(
            '/odoo/action-eh_account_reconcile_pro.action_eh_reconciliation_exception_wizard',
            [{'wait': '.o_form_view [name="journal_ids"]'}],
        )

    def test_statement_list_review_button_icon(self):
        self.env['account.bank.statement'].create({
            'name': 'EHWEB statement',
            'journal_id': self.journal.id,
            'line_ids': [(4, self.statement_line.id)],
        })
        self._check_screen(
            '/odoo/action-account.action_bank_statement_tree',
            [{
                'wait': '.o_list_view button[name="action_view_eh_unmatched_lines"]'
                        ' i.oi[data-icon="search"]',
            }],
        )
