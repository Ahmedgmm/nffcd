import json

from odoo import Command, fields
from odoo.tests import tagged
from odoo.exceptions import ValidationError, UserError
from odoo.addons.eh_account_base.tests.common import EhAccountIntegrationTestCase


@tagged('post_install', '-at_install', 'nffcd_settlement')
class TestSettlement(EhAccountIntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.handler = self.env['eh.account.dynamic.report.handler.settlement_trial_balance']
        self.options = {'date': {'date_from': '2026-01-01', 'date_to': '2026-12-31'},
                        'company_ids': self.company.ids, 'posted_only': True, 'show_zero': True}
        self.settlement = self.env['account.journal'].create({'name': 'Test Settlements', 'code': 'STST',
                            'type': 'settlement', 'company_id': self.company.id})

    def move(self, journal=None, amount=100, date='2026-06-15', opening=False, post=True):
        move = self.env['account.move'].create({'journal_id': (journal or self.journal_misc).id,
            'move_type': 'entry', 'date': date, 'ref': 'Reviewed correction / test', 'settlement_opening': opening,
            'line_ids': [Command.create({'account_id': self.account_cash.id, 'debit': amount}),
                         Command.create({'account_id': self.account_revenue.id, 'credit': amount})]})
        if post:
            move.action_post()
        return move

    def values(self, result, aid):
        line = next(l for l in result['lines'] if l.get('meta', {}).get('account_id') == aid)
        return {c['expression_label']: c['value'] for c in line['columns']}

    def test_settlement_dashboard(self):
        self.move(self.settlement, post=False)
        self.move(self.settlement)
        journals = self.settlement | self.journal_misc
        journals = journals.with_context(allowed_company_ids=self.company.ids)
        for journal in journals:
            data = json.loads(journal.kanban_dashboard)
            self.assertEqual(data['drag_drop_settings']['image'], '/web/static/img/folder.svg')
            self.assertTrue(data['drag_drop_settings']['text'])
        self.assertEqual(json.loads(journals[0].kanban_dashboard)['number_draft'], 1)

    def test_journal_rule_opening_gross_and_standard_unchanged(self):
        self.move(amount=75, date='2026-01-01', opening=True)
        self.move(amount=120)
        self.move(self.settlement, amount=30)
        options = dict(self.options, account_ids=self.account_cash.ids)
        result = self.handler.compute(options)
        values = self.values(result, self.account_cash.id)
        self.assertEqual(len(result['columns']), 9)
        self.assertEqual(values['opening_debit'], 75)
        self.assertEqual(values['period_debit'], 120)
        self.assertEqual(values['settlement_debit'], 30)
        self.assertEqual(values['closing_debit'], 225)
        standard = self.env['eh.account.dynamic.report.handler.trial_balance'].compute(options)
        self.assertEqual(len(standard['columns']), 7)
        self.assertEqual(self.values(standard, self.account_cash.id)['period_debit'], 225)
        self.assertEqual(values['closing_debit'], self.values(standard, self.account_cash.id)['closing_debit'])

    def test_legacy_misc_never_becomes_settlement(self):
        move = self.move(amount=22)
        self.env['nffcd.legacy.purpose'].create({'move_id': move.id, 'purpose': 'financial', 'evidence': 'Reviewed mixed import journal evidence'})
        result = self.handler.compute(dict(self.options, account_ids=self.account_cash.ids))
        self.assertEqual(self.values(result, self.account_cash.id)['settlement_debit'], 0)

    def test_later_opening_and_drafts(self):
        self.move(self.settlement, date='2026-01-10', amount=20)
        self.move(self.settlement, amount=9, post=False)
        options = dict(self.options, date={'date_from': '2026-02-01', 'date_to': '2026-12-31'}, account_ids=self.account_cash.ids)
        self.assertEqual(self.values(self.handler.compute(options), self.account_cash.id)['opening_debit'], 20)
        self.assertEqual(self.values(self.handler.compute(dict(options, posted_only=False)), self.account_cash.id)['settlement_debit'], 9)

    def test_drilldowns_match(self):
        self.move(amount=50, date='2026-01-01', opening=True)
        self.move(amount=120)
        self.move(self.settlement, amount=30)
        options = dict(self.options, account_ids=self.account_cash.ids)
        result = self.handler.compute(options)
        values = self.values(result, self.account_cash.id)
        for expression, value in values.items():
            action = self.handler.get_drilldown_action(dict(options, _eh_column_expression=expression), 'account-%s' % self.account_cash.id)
            lines = self.env['account.move.line'].search(action['domain'])
            if expression.startswith(('period_', 'settlement_')):
                actual = sum(lines.mapped(expression.rsplit('_', 1)[-1]))
            else:
                net = sum(lines.mapped('balance'))
                actual = max(net if expression.endswith('_debit') else -net, 0)
            self.assertAlmostEqual(actual, value, places=2)

    def test_hierarchy_equation_and_journal_filter(self):
        self.move(self.settlement, amount=30)
        result = self.handler.compute(dict(self.options, journal_ids=self.settlement.ids))
        for values in [result['totals']] + [{c['expression_label']: c['value'] for c in l['columns']} for l in result['lines']]:
            self.assertAlmostEqual(values['opening_debit'] - values['opening_credit'] + values['period_debit'] - values['period_credit'] + values['settlement_debit'] - values['settlement_credit'], values['closing_debit'] - values['closing_credit'], places=2)
        self.assertEqual(result['totals']['period_debit'], 0)

    def test_purpose_and_used_journal_guards(self):
        self.move(self.settlement)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.settlement.type = 'general'
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.move(self.settlement, opening=True)
        with self.assertRaises(UserError):
            self.handler.compute(dict(self.options, comparison='previous_year'))

    def test_unpaid_invoice_and_bill_are_financial(self):
        for move_type, journal, account in [('out_invoice', self.journal_sale, self.account_revenue),
                                           ('in_invoice', self.journal_purchase, self.account_expense)]:
            invoice = self.env['account.move'].create({'move_type': move_type, 'journal_id': journal.id,
                'partner_id': self.partner_a.id, 'invoice_date': '2026-06-15', 'date': '2026-06-15',
                'invoice_line_ids': [Command.create({'name': 'Unpaid operational invoice', 'account_id': account.id,
                    'quantity': 1, 'price_unit': 100, 'tax_ids': [Command.clear()]})]})
            invoice.action_post()
            self.assertEqual(invoice.state, 'posted')
            result = self.handler.compute(dict(self.options, journal_ids=journal.ids))
            self.assertEqual(result['totals']['settlement_debit'], 0)
            self.assertEqual(result['totals']['period_debit'], 100)

    def test_reversal_and_cancelled(self):
        move = self.move(self.settlement, amount=40)
        reverse = move._reverse_moves([{'date': '2026-07-01', 'ref': 'Reversal of reviewed adjustment'}])
        reverse.action_post()
        self.assertEqual(reverse.journal_id, self.settlement)
        result = self.handler.compute(dict(self.options, account_ids=self.account_cash.ids))
        values = self.values(result, self.account_cash.id)
        self.assertEqual(values['settlement_debit'], 40)
        self.assertEqual(values['settlement_credit'], 40)
        self.assertEqual(values['closing_debit'], 0)
        draft = self.move(self.settlement, amount=12, post=False)
        draft.button_cancel()
        result = self.handler.compute(dict(self.options, account_ids=self.account_cash.ids, posted_only=False))
        self.assertEqual(self.values(result, self.account_cash.id)['settlement_debit'], 40)

    def test_cache_invalidation_and_posted_rows_unchanged(self):
        move = self.move(amount=50, date='2026-01-01')
        before = move.read(['name', 'date', 'journal_id', 'state', 'ref', 'write_date'])
        report = self.env.ref('nffcd_settlement.report_settlement_trial_balance')
        first = report.render(self.options)
        mapping = self.env['nffcd.legacy.purpose'].create({'move_id': move.id, 'purpose': 'opening',
                                                        'evidence': 'Reviewed first-day opening source'})
        second = report.render(self.options)
        self.assertFalse(second['from_cache'])
        self.assertEqual(self.values(second, self.account_cash.id)['opening_debit'], 50)
        self.assertEqual(before, move.read(['name', 'date', 'journal_id', 'state', 'ref', 'write_date']))
        self.assertEqual(self.values(first, self.account_cash.id)['period_debit'], 50)

    def test_exports_have_eight_values(self):
        import io
        import openpyxl
        self.move(self.settlement, amount=123)
        report = self.env.ref('nffcd_settlement.report_settlement_trial_balance')
        result = report.render(self.options)
        workbook = openpyxl.load_workbook(io.BytesIO(report.render_xlsx(self.options)), data_only=True)
        sheet = workbook.active
        row = next(row for row in sheet.iter_rows(values_only=True) if row[0] and '1000' in str(row[0]) and 'Cash' in str(row[0]))
        expected = list(self.values(result, self.account_cash.id).values())
        self.assertEqual(list(row[1:9]), expected)
        html = report.render_pdf(self.options)
        if html[:4] != b'%PDF':
            self.assertIn(b'123', html)
            self.assertIn(b'Current-period Settlements', html)

    def test_bank_and_cash_journals_are_financial(self):
        for code, kind in [('TBK', 'bank'), ('TCS', 'cash')]:
            journal = self.env['account.journal'].create({'name': 'Operational ' + kind, 'type': kind,
                'code': code, 'company_id': self.company.id, 'default_account_id': self.account_cash.id})
            self.move(journal, amount=27)
            result = self.handler.compute(dict(self.options, journal_ids=journal.ids))
            self.assertEqual(result['totals']['period_debit'], 27)
            self.assertEqual(result['totals']['settlement_debit'], 0)

    def test_multicompany_and_classification_access(self):
        from odoo.tests import new_test_user
        from odoo.exceptions import AccessError
        other = self.env['res.company'].create({'name': 'Isolated other company'})
        user = new_test_user(self.env, login='settlement.limited', groups='account.group_account_user,eh_account_base.group_eh_user',
                             company_id=self.company.id)
        restricted = self.handler.with_user(user).with_context(allowed_company_ids=self.company.ids)
        with self.assertRaises(AccessError):
            restricted.compute(dict(self.options, company_ids=other.ids))
        move = self.move()
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env['nffcd.legacy.purpose'].with_user(user).create({'move_id': move.id, 'purpose': 'opening', 'evidence': 'Restricted user cannot reclassify'})

    def test_opening_and_ending_are_net(self):
        self.move(amount=100, date='2026-01-01', opening=True)
        move = self.env['account.move'].create({'journal_id':self.journal_misc.id, 'move_type':'entry',
            'date':'2026-01-01', 'ref':'Opening credit balance component', 'settlement_opening':True,
            'line_ids':[Command.create({'account_id':self.account_cash.id,'credit':60}),
                        Command.create({'account_id':self.account_equity.id,'debit':60})]})
        move.action_post()
        result = self.handler.compute(dict(self.options, account_ids=self.account_cash.ids))
        values = self.values(result, self.account_cash.id)
        self.assertEqual(values['opening_debit'],40)
        self.assertEqual(values['opening_credit'],0)
        self.assertEqual(values['period_debit'],0)
        self.assertEqual(values['closing_debit'],40)

    def test_group_and_total_drilldowns(self):
        parent = self.env['account.account'].create({'name':'Cash heading', 'code':'1900', 'account_type':'asset_current', 'company_ids':[Command.set(self.company.ids)]})
        self.account_cash.parent_id = parent
        self.move(amount=50, date='2026-01-01', opening=True)
        self.move(self.settlement, amount=30)
        result = self.handler.compute(self.options)
        group = next(line for line in result['lines'] if line.get('meta', {}).get('group_id') == parent.id)
        rows = [(group['id'], {c['expression_label']:c['value'] for c in group['columns']}), ('settlement-total',result['totals'])]
        for line_id, values in rows:
            for expression, value in values.items():
                action = self.handler.get_drilldown_action(dict(self.options, _eh_column_expression=expression), line_id)
                lines = self.env['account.move.line'].search(action['domain'])
                if expression.startswith(('period_', 'settlement_')):
                    actual = sum(lines.mapped(expression.rsplit('_',1)[-1]))
                else:
                    net = sum(lines.mapped('balance'))
                    actual = net if expression.endswith('_debit') else -net
                self.assertAlmostEqual(actual, value, places=2)

    def test_retained_earnings_drilldown(self):
        retained = self.env['account.account'].create({'name':'Retained Earnings', 'code':'3999', 'account_type':'equity_unaffected', 'company_ids':[Command.set(self.company.ids)]})
        self.move(amount=200, date='2025-06-15')
        options = dict(self.options, account_ids=retained.ids)
        result = self.handler.compute(options)
        values = self.values(result, retained.id)
        self.assertEqual(values['opening_credit'],200)
        action = self.handler.get_drilldown_action(dict(options,_eh_column_expression='opening_credit'),'account-%s'%retained.id)
        self.assertEqual(-sum(self.env['account.move.line'].search(action['domain']).mapped('balance')),200)

    def test_arabic_headings_and_column_order(self):
        self.env['res.lang']._activate_lang('ar_001')
        result = self.handler.with_context(lang='ar_001').compute(self.options)
        self.assertEqual(result['column_header_rows'][0][3]['name'], 'التسويات خلال الفترة')
        self.assertEqual([col['expression_label'] for col in result['columns'][5:7]], ['settlement_debit','settlement_credit'])

    def test_settlement_action_defaults_and_explanation(self):
        move = self.env['account.move'].with_context(nffcd_settlement_journal=True).new({'move_type':'entry','company_id':self.company.id})
        self.assertEqual(move._search_default_journal(),self.settlement)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['account.move'].create({'move_type':'entry','journal_id':self.settlement.id,'ref':'x'})

    def test_standard_entry_dropdown_includes_settlement_journal(self):
        move = self.env['account.move'].new({'move_type':'entry', 'company_id':self.company.id})
        self.assertIn(self.settlement, move.suitable_journal_ids._origin)
        self.assertIn(self.journal_misc, move.suitable_journal_ids._origin)
        for move_type in ('out_invoice', 'in_invoice', 'out_refund', 'in_refund'):
            self.assertNotIn(self.settlement, self.env['account.move']._get_suitable_journal_ids(move_type, self.company))
        other = self.env['res.company'].create({'name':'Settlement selector isolation'})
        self.assertNotIn(self.settlement, self.env['account.move']._get_suitable_journal_ids('entry', other))
