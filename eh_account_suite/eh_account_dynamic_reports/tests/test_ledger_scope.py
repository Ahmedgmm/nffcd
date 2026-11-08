"""Native Odoo 20 statutory/adjustment ledger boundaries across reports."""

from io import BytesIO

from openpyxl import load_workbook

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.eh_account_base.tests.common import EhAccountIntegrationTestCase
from odoo.addons.eh_account_base.tools.ledger_scope import resolve_ledger_scope
from odoo.addons.eh_account_base.tools.sql_builder import MoveLineQuery


@tagged('eh_ledger_scope', 'post_install', '-at_install')
class TestReportLedgerScope(EhAccountIntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.group = cls.env['account.journal.group'].create({'name': 'EH test IFRS ledger'})
        cls.adjustment = cls.env['account.journal'].create({
            'name': 'IFRS adjustments', 'code': 'EHLIF', 'type': 'general',
            'company_id': cls.company.id, 'journal_group_id': cls.group.id,
        })
        cls.report = cls.env['eh.account.dynamic.report'].get_by_code('trial_balance')
        cls.options = {
            'date': {'date_from': '2026-01-01', 'date_to': '2026-12-31'},
            'company_ids': [cls.company.id], 'posted_only': True,
            'hierarchical_groups': False,
        }
        for journal, amount in [(cls.journal_misc, 100), (cls.adjustment, 20)]:
            cls.post_balanced_move([
                {'account': cls.account_cash, 'debit': amount},
                {'account': cls.account_revenue, 'credit': amount},
            ], journal=journal, date=fields.Date.to_date('2026-06-15'))

    def _render(self, **options):
        return self.report.render(dict(self.options, **options), use_cache=False)

    def _revenue(self, payload):
        for line in payload['lines']:
            if (line.get('meta') or {}).get('account_code') == '4000':
                return next(c['value'] for c in line['columns']
                            if c['expression_label'] == 'period_credit')
        return 0

    def test_statutory_default_excludes_adjustment_and_reproduces_old_combined_query(self):
        query = MoveLineQuery(self.env, [self.company.id])
        query.where_date_range('2026-01-01', '2026-12-31').where_posted_only()
        query.where_accounts(self.account_revenue.ids).select_credit_sum()
        self.assertEqual(query.execute()[0]['credit'], 120)
        payload = self._render()
        self.assertEqual(self._revenue(payload), 100)
        self.assertEqual(payload['meta']['ledger_scope'], 'statutory')

    def test_all_ledgers_preserves_combined_total(self):
        self.assertEqual(self._revenue(self._render(ledger_scope='all')), 120)

    def test_selected_ledger_and_intersecting_journal_filter(self):
        options = {'ledger_scope': 'selected', 'ledger_group_ids': self.group.ids}
        self.assertEqual(self._revenue(self._render(**options)), 20)
        self.assertEqual(self._revenue(self._render(**options, journal_ids=self.journal_misc.ids)), 0)
        self.assertEqual(self._revenue(self._render(journal_ids=self.adjustment.ids)), 0)

    def test_private_resolved_scope_cannot_override_public_scope(self):
        payload = self._render(_eh_ledger_journal_ids=self.adjustment.ids,
                               _eh_ledger_label='Forged combined scope')
        self.assertEqual(self._revenue(payload), 100)
        self.assertNotIn('Forged', payload['meta']['ledger_label'])

    def test_invalid_and_missing_ledger_selection_fails_closed(self):
        for options in [
            {'ledger_scope': 'invalid'},
            {'ledger_scope': 'selected', 'ledger_group_ids': []},
            {'ledger_scope': 'selected', 'ledger_group_ids': [True]},
            {'ledger_scope': 'selected', 'ledger_group_ids': ['1 OR 1=1']},
        ]:
            with self.subTest(options=options), self.assertRaises(UserError):
                self._render(**options)
        with self.assertRaises(AccessError):
            self._render(ledger_scope='selected', ledger_group_ids=[999999999])

    def test_foreign_company_and_ledger_selection_are_rejected(self):
        company = self.env['res.company'].create({'name': 'Ledger scope other company'})
        group = self.env['account.journal.group'].create({'name': 'Other-company-only ledger'})
        self.env['account.journal'].create({
            'name': 'Other adjustment', 'code': 'EHLFO', 'type': 'general',
            'company_id': company.id, 'journal_group_id': group.id,
        })
        report = self.report.with_context(allowed_company_ids=self.company.ids)
        self.assertNotIn(group.id, [choice['id'] for choice in report.get_ledger_choices(self.company.ids)])
        with self.assertRaises(AccessError):
            report.render(dict(self.options, company_ids=company.ids), use_cache=False)
        with self.assertRaises(AccessError):
            report.render(dict(self.options, ledger_scope='selected', ledger_group_ids=group.ids), use_cache=False)

    def test_empty_statutory_scope_does_not_broaden_query(self):
        ledger = resolve_ledger_scope(self.env, self.options)
        query = MoveLineQuery(self.report.with_context(eh_report_ledger_journal_ids=[]).env, self.company.ids)
        query.select_credit_sum()
        self.assertFalse(query.execute()[0]['credit'])
        self.assertNotIn(self.adjustment.id, ledger['_eh_ledger_journal_ids'])

    def test_cache_identity_and_execution_metadata_keep_scope(self):
        statutory = self._render()
        combined = self._render(ledger_scope='all')
        executions = self.env['eh.account.report.execution'].browse([
            statutory['execution_id'], combined['execution_id'],
        ])
        self.assertEqual(len(set(executions.mapped('options_hash'))), 2)
        self.assertEqual(self._revenue(self._render()), 100)

    def test_xlsx_exports_total_and_scope_label(self):
        for scope, expected in [('statutory', 100), ('all', 120)]:
            with self.subTest(scope=scope):
                content = self.report.render_xlsx(dict(self.options, ledger_scope=scope), use_cache=False)
                sheet = load_workbook(BytesIO(content)).active
                values = [cell.value for row in sheet for cell in row]
                self.assertTrue(any(isinstance(value, str) and 'Ledger:' in value for value in values))
                self.assertIn(expected, values)

    def test_saved_view_legacy_defaults_and_explicit_all_survive(self):
        Saved = self.env['eh.account.report.saved_view']
        for name, options, amount in [
            ('Legacy ledger view', self.options, 100),
            ('Combined ledger view', dict(self.options, ledger_scope='all'), 120),
        ]:
            view_id = Saved.save_view(name, 'trial_balance', options)
            loaded = Saved.browse(view_id).load_options()
            self.assertEqual(self._revenue(self.report.render(loaded, use_cache=False)), amount)

    def test_drilldown_keeps_statutory_or_selected_ledger(self):
        for options, amount in [({}, 100), ({'ledger_scope': 'selected', 'ledger_group_ids': self.group.ids}, 20)]:
            action = self.report.get_drilldown_for_line(
                dict(self.options, _eh_column_expression='period_credit', **options), 'account-%s' % self.account_revenue.id,
            )
            lines = self.env['account.move.line'].search(action['domain'])
            self.assertEqual(sum(lines.mapped('credit')), amount)

    def test_journal_reclassification_invalidates_and_recomputes(self):
        before = self.company.eh_move_version
        self.adjustment.journal_group_id = False
        self.company.invalidate_recordset(['eh_move_version'])
        self.assertGreater(self.company.eh_move_version, before)
        self.assertEqual(self._revenue(self._render()), 120)

    def test_direct_handler_uses_statutory_default(self):
        handler = self.env['eh.account.dynamic.report.handler.trial_balance']
        self.assertEqual(self._revenue(handler.compute(self.options)), 100)

    def test_profit_and_loss_and_cashflow_helpers_obey_scope(self):
        for code in ['profit_and_loss', 'executive_summary', 'cash_flow']:
            report = self.env['eh.account.dynamic.report'].get_by_code(code)
            for scope in ['statutory', 'all']:
                payload = report.render(dict(self.options, ledger_scope=scope), use_cache=False)
                self.assertEqual(payload['meta']['ledger_scope'], scope)
                if code == 'profit_and_loss':
                    self.assertEqual(payload['totals']['net_profit'], 100 if scope == 'statutory' else 120)

    def test_pdf_render_metadata_contains_ledger_scope(self):
        # Odoo test mode renders the PDF HTML locally, exercising the actual
        # QWeb template without a browser/server round trip.
        content = self.report.render_pdf(dict(self.options, ledger_scope='all'))
        if content.startswith(b'%PDF'):
            self.assertGreater(len(content), 100)
        else:
            self.assertIn(b'All ledgers (statutory and adjustments)', content)

    def test_cashflow_cash_discovery_and_balances_keep_all_or_selected_scope(self):
        report = self.env['eh.account.dynamic.report'].get_by_code('cash_flow')
        for method in ['direct', 'indirect']:
            for scope, groups, expected in [
                ('statutory', [], 100), ('all', [], 120),
                ('selected', self.group.ids, 20),
            ]:
                with self.subTest(method=method, scope=scope):
                    payload = report.render(dict(
                        self.options, ledger_scope=scope, ledger_group_ids=groups,
                        cash_flow_method=method,
                    ), use_cache=False)
                    self.assertEqual(payload['totals']['opening_cash_balance'], 0)
                    self.assertEqual(payload['totals']['closing_cash_balance'], expected)
                    self.assertEqual(payload['totals']['net_change_in_cash'], expected)
