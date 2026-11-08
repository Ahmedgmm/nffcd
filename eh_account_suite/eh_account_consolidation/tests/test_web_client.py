# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Browser smoke test of every consolidation view on the Odoo 20 web client.

Installing the module validates each view arch, but only a browser proves
that the list, form, graph and pivot views render, that the stat and row
buttons show their Material Symbols now that Font Awesome is gone, and that
the drill-down actions open. Any console error, error dialog or leftover
Font Awesome element fails the test.
"""

import json
import unittest

from odoo.tests import HttpCase, tagged

from .common import make_account, make_general_journal, post_move

try:
    # Odoo's headless Chrome driver talks to the browser through it; without
    # it the framework would log a warning per test before skipping.
    import websocket
except ImportError:
    websocket = None

# Each step waits for a selector, checks forbidden selectors, then
# optionally clicks the element. Any console error fails the test.
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

_NO_FA = ['.o_action_manager .fa']


@tagged('eh_account_consolidation', 'post_install', '-at_install')
@unittest.skipIf(
    websocket is None,
    "websocket-client is required to drive headless Chrome",
)
class TestConsolidationWebClient(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        parent = cls.env.company
        currency = parent.currency_id
        subsidiary = cls.env['res.company'].create({
            'name': 'Web Client Subsidiary',
            'currency_id': currency.id,
        })
        ledger = cls.env['res.company'].create({
            'name': 'Web Client Consolidation Ledger',
            'currency_id': currency.id,
        })
        admin = cls.env.ref('base.user_admin')
        admin.write({
            'company_ids': [(4, subsidiary.id), (4, ledger.id)],
            'group_ids': [
                (4, cls.env.ref('eh_account_base.group_eh_manager').id),
            ],
        })
        if 'tour_enabled' in admin._fields:
            admin.tour_enabled = False
        source_cash = make_account(
            cls.env, subsidiary, 'WCA100', 'Web Cash', 'asset_current')
        source_income = make_account(
            cls.env, subsidiary, 'WIN400', 'Web Revenue', 'income')
        source_journal = make_general_journal(cls.env, subsidiary)
        make_account(
            cls.env, ledger, 'WCA100', 'Web Cash', 'asset_current')
        make_account(
            cls.env, ledger, 'WIN400', 'Web Revenue', 'income')
        ledger_journal = make_general_journal(cls.env, ledger)
        post_move(
            cls.env, subsidiary, source_journal, '2026-06-30', [
                (source_cash, 400.0, 0.0, False),
                (source_income, 0.0, 400.0, False),
            ],
        )
        cls.entity = cls.env['eh.consol.entity'].create({
            'name': 'Web Client Group',
            'code': 'web_client_group',
            'parent_company_id': parent.id,
            'presentation_currency_id': currency.id,
            'consolidation_company_id': ledger.id,
            'consolidation_journal_id': ledger_journal.id,
            'member_ids': [(0, 0, {
                'company_id': subsidiary.id,
                'ownership_pct': 100.0,
                'method': 'full',
            })],
        })
        scope = cls.env(context=dict(
            cls.env.context,
            allowed_company_ids=[parent.id, subsidiary.id, ledger.id],
        ))
        cls.consol_run = scope['eh.consol.run'].create({
            'entity_id': cls.entity.id,
            'period_from': '2026-01-01',
            'period_to': '2026-12-31',
        })
        cls.consol_run.action_compute()
        cls.cids = '-'.join(
            map(str, (parent.id, subsidiary.id, ledger.id)),
        )

    def _check_screen(self, url, steps):
        self.browser_js(
            url,
            _SCREEN_CHECK % json.dumps(steps),
            'odoo.isReady === true',
            login='admin',
            timeout=120,
            cookies={'cids': self.cids},
        )

    def test_entity_views_and_buttons(self):
        action = '/odoo/action-eh_account_consolidation.action_eh_consol_entity'
        self._check_screen(action, [
            {'wait': '.o_list_view .o_data_row', 'forbid': _NO_FA},
        ])
        self._check_screen('%s/%s' % (action, self.entity.id), [
            {
                'wait': 'button[name="action_view_members"]'
                        ' i.oi[data-icon="account_tree"]',
                'forbid': _NO_FA,
            },
            {
                'wait': 'button[name="action_view_runs"]'
                        ' i.oi[data-icon="show_chart"]',
            },
            {
                'wait': 'button[name="action_dispose_member"]'
                        ' i.oi[data-icon="logout"]',
            },
            {'wait': 'button[name="action_view_runs"]', 'click': True},
            {'wait': '.o_list_view .o_data_row', 'forbid': _NO_FA},
        ])
        self._check_screen('%s/new' % action, [
            {'wait': '.o_form_view .o_field_widget[name="name"] input'},
        ])

    def test_run_views_buttons_and_trial_balance(self):
        action = '/odoo/action-eh_account_consolidation.action_eh_consol_run'
        for view_type, selector in (
            ('list', '.o_list_view .o_data_row'),
            ('graph', '.o_graph_view .o_graph_renderer'),
            ('pivot', '.o_pivot_view .o_pivot'),
        ):
            with self.subTest(view_type=view_type):
                self._check_screen(
                    '%s?view_type=%s' % (action, view_type),
                    [{'wait': selector, 'forbid': _NO_FA}],
                )
        self._check_screen('%s/%s' % (action, self.consol_run.id), [
            {
                'wait': 'button[name="action_view_lines"]'
                        ' i.oi[data-icon="format_list_bulleted"]',
                'forbid': _NO_FA,
            },
            {
                'wait': 'button[name="action_view_eliminations"]'
                        ' i.oi[data-icon="content_cut"]',
            },
            {
                'wait': 'button[name="action_view_trial_balance"]'
                        ' i.oi[data-icon="balance"]',
                'click': True,
            },
            {
                'wait': '.o_list_view button[name="action_drilldown"]'
                        ' i.oi[data-icon="zoom_in"]',
                'forbid': _NO_FA,
            },
            {
                'wait': '.o_list_view button[name="action_drilldown"]',
                'click': True,
            },
            {'wait': '.o_list_view .o_data_row', 'forbid': _NO_FA},
        ])
        self._check_screen('%s/%s' % (action, self.consol_run.id), [
            {'wait': 'button[name="action_view_lines"]', 'click': True},
            {'wait': '.o_list_view .o_data_row', 'forbid': _NO_FA},
        ])

    def test_elimination_views(self):
        action = (
            '/odoo/action-eh_account_consolidation.action_eh_consol_elimination'
        )
        self._check_screen(action, [
            {'wait': '.o_list_view', 'forbid': _NO_FA},
        ])
        self._check_screen('%s/new' % action, [
            {'wait': '.o_form_view .o_form_sheet', 'forbid': _NO_FA},
        ])
