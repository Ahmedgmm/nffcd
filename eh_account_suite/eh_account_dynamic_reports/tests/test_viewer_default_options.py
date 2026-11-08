# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Handler defaults the viewer applies before its first render.

The viewer opens on month to date with every filter empty. A handler that
defines its own default (a statement type, a quarter) must reach the first
render, while a report without a custom default must open exactly as
before, so only the keys that differ from the generic handler defaults are
handed to the viewer.
"""

from odoo.exceptions import AccessError
from odoo.tests import new_test_user, tagged

from odoo.addons.eh_account_base.tests.common import EhAccountUnitTestCase


# These reports keep generic period/filter defaults. The three supported
# financial reports now explicitly advertise the hierarchy layout default.
GENERIC_DEFAULT_REPORTS = (
    'executive_summary',
    'deferred_revenue',
    'deferred_expense',
    'bank_reconciliation',
    'trial_balance',
    'profit_and_loss',
    'balance_sheet',
    'general_ledger',
    'partner_ledger',
    'aged_receivable',
    'aged_payable',
    'cash_flow',
    'analytic_balance',
)


@tagged('eh_account_dynamic_reports', 'post_install', '-at_install')
class TestViewerDefaultOptions(EhAccountUnitTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Report = cls.env['eh.account.dynamic.report']

    def _report(self, code):
        report = self.Report.search([('code', '=', code)], limit=1)
        self.assertTrue(report, "report %s is not registered" % code)
        return report

    def test_reports_without_custom_default_keep_viewer_defaults(self):
        for code in GENERIC_DEFAULT_REPORTS:
            with self.subTest(report=code):
                self.assertEqual(
                    self._report(code).get_viewer_default_options(),
                    {'hierarchical_groups': True} if code in {
                        'trial_balance', 'profit_and_loss', 'balance_sheet',
                    } else {},
                )

    def test_statement_defaults_reach_the_viewer_without_generic_keys(self):
        for code in ('customer_statement', 'vendor_statement'):
            with self.subTest(report=code):
                defaults = self._report(code).get_viewer_default_options()
                self.assertEqual(defaults, {
                    'statement_type': 'open_item',
                    'partner_id': False,
                })

    def test_custom_default_period_is_returned(self):
        report = self._report('trial_balance')
        handler_cls = type(self.env[report.handler_model])
        original = handler_cls.build_default_options

        def build_default_options(handler):
            options = original(handler)
            options['date'] = {
                'mode': 'range',
                'date_from': '2026-07-01',
                'date_to': '2026-09-30',
            }
            options['posted_only'] = False
            return options

        self.patch(handler_cls, 'build_default_options', build_default_options)
        self.assertEqual(report.get_viewer_default_options(), {
            'date': {
                'mode': 'range',
                'date_from': '2026-07-01',
                'date_to': '2026-09-30',
            },
            'posted_only': False,
            'hierarchical_groups': True,
        })

    def test_defaults_require_read_access_to_the_report(self):
        outsider = new_test_user(
            self.env,
            login='eh_viewer_defaults_outsider',
            groups='base.group_user',
        )
        report = self._report('trial_balance').with_user(outsider)
        with self.assertRaises(AccessError):
            report.get_viewer_default_options()
