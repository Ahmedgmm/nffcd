"""Account hierarchy contracts through the real report/export pipeline."""

from io import BytesIO

from openpyxl import load_workbook

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import new_test_user, tagged

from odoo.addons.eh_account_base.tests.common import EhAccountIntegrationTestCase


@tagged('eh_parent_accounts', 'post_install', '-at_install')
class TestParentAccountContract(EhAccountIntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reports = {
            code: cls.env['eh.account.dynamic.report'].get_by_code(code)
            for code in ['trial_balance', 'profit_and_loss', 'balance_sheet', 'general_ledger']
        }
        Account = cls.env['account.account']
        cls.chains = {}
        for kind, leaf, prefix in [
            ('asset_current', cls.account_cash, '98'),
            ('income', cls.account_revenue, '97'),
        ]:
            chain = Account.browse()
            for depth in range(3):
                parent = Account.create({
                    'name': '%s ancestor %s' % (kind, depth),
                    'code': prefix + str(depth), 'account_type': kind,
                    'company_ids': [(6, 0, cls.company.ids)],
                    'parent_id': chain[-1:].id,
                })
                chain |= parent
            leaf.parent_id = chain[-1].id
            cls.chains[kind] = chain
        cls.group = cls.env['account.journal.group'].create({'name': 'Parent test adjustments'})
        cls.adjustment = cls.env['account.journal'].create({
            'name': 'Parent adjustments', 'code': 'PARAJ', 'type': 'general',
            'company_id': cls.company.id, 'journal_group_id': cls.group.id,
        })
        for year, journal, leaf_amount, own_amount in [
            (2025, cls.journal_misc, 40, 10),
            (2026, cls.journal_misc, 100, 30),
            (2026, cls.adjustment, 20, 5),
        ]:
            cls.post_balanced_move([
                {'account': cls.account_cash, 'debit': leaf_amount},
                {'account': cls.account_revenue, 'credit': leaf_amount},
                {'account': cls.chains['asset_current'][1], 'debit': own_amount},
                {'account': cls.chains['income'][1], 'credit': own_amount},
            ], journal=journal, date=fields.Date.to_date('%s-06-15' % year))
        # Archived parent accounts must still expose their historical own
        # postings separately from descendant totals.
        for chain in cls.chains.values():
            chain.active = False
        cls.options = {
            'date': {'date_from': '2026-01-01', 'date_to': '2026-12-31'},
            'company_ids': cls.company.ids, 'posted_only': True,
            'show_zero': False, 'hierarchical_groups': True,
        }

    def _render(self, code='profit_and_loss', **extra):
        return self.reports[code].render(dict(self.options, **extra), use_cache=False)

    def _groups(self, payload):
        return [line for line in payload['lines'] if line.get('meta', {}).get('kind') == 'account_group']

    def _assert_parent_sums(self, payload):
        groups = self._groups(payload)
        self.assertTrue(groups)
        for group in groups:
            children = [line for line in payload['lines'] if line.get('parent_id') == group['id']]
            self.assertTrue(children, group['id'])
            for index, column in enumerate(group['columns']):
                # Percentage columns are ratios, not additive amounts.
                if column.get('figure_type') == 'percentage' or any(token in column['expression_label'] for token in ('percent', '_pct')):
                    continue
                value = column.get('value')
                if isinstance(value, (int, float)):
                    total = sum(child['columns'][index].get('value') or 0 for child in children)
                    self.assertAlmostEqual(value, total, places=2, msg=group['id'])

    def test_three_ancestors_and_archived_parent_own_postings(self):
        for code in ['trial_balance', 'profit_and_loss', 'balance_sheet']:
            with self.subTest(code=code):
                payload = self._render(code)
                self._assert_parent_sums(payload)
                ids = {line['id']: line for line in payload['lines']}
                for kind in (['income'] if code == 'profit_and_loss' else ['asset_current']):
                    chain = self.chains[kind]
                    groups = {line['meta']['group_id']: line for line in self._groups(payload)}
                    self.assertTrue(set(chain.ids).issubset(groups))
                    self.assertEqual(groups[chain[2].id]['parent_id'], groups[chain[1].id]['id'])
                    self.assertEqual(groups[chain[1].id]['parent_id'], groups[chain[0].id]['id'])
                    own = ids['account-%s' % chain[1].id]
                    self.assertEqual(own['parent_id'], groups[chain[1].id]['id'])
                    self.assertGreater(own['level'], groups[chain[1].id]['level'])

    def test_zero_net_ancestor_keeps_offsetting_nonzero_children(self):
        opposite = self.env['account.account'].create({
            'name': 'Contra income offset', 'code': '9799', 'account_type': 'income',
            'parent_id': self.chains['income'][2].id,
            'company_ids': [(6, 0, self.company.ids)],
        })
        self.post_balanced_move([
            {'account': opposite, 'debit': 130},
            {'account': self.account_cash, 'credit': 130},
        ], date=fields.Date.to_date('2026-07-01'))
        payload = self._render()
        self._assert_parent_sums(payload)
        root = next(line for line in self._groups(payload)
                    if line['meta']['group_id'] == self.chains['income'][0].id)
        self.assertEqual(root['columns'][0]['value'], 0)
        self.assertIn('account-%s' % opposite.id, [line['id'] for line in payload['lines']])

    def test_ledger_period_comparison_and_presentation_currency_preserve_rollups(self):
        currency = self.env['res.currency'].create({'name': 'PHR', 'symbol': 'H', 'rounding': 0.01})
        self.env['res.currency.rate'].create({
            'currency_id': currency.id, 'company_id': self.company.id,
            'name': '2024-01-01', 'rate': 2,
        })
        for scope, groups, amount in [('statutory', [], 130), ('all', [], 155), ('selected', self.group.ids, 25)]:
            with self.subTest(scope=scope):
                payload = self._render(ledger_scope=scope, ledger_group_ids=groups,
                                       comparison='previous_year', presentation_currency_id=currency.id)
                self._assert_parent_sums(payload)
                root = next(line for line in self._groups(payload)
                            if line['meta']['group_id'] == self.chains['income'][0].id)
                self.assertEqual(root['columns'][0]['value'], amount * 2)
                self.assertEqual(payload['meta']['ledger_scope'], scope)
        empty = self._render(date={'date_from': '2026-01-01', 'date_to': '2026-05-31'})
        self.assertFalse(self._groups(empty))

    def test_capability_defaults_strict_choice_and_unsupported_normalization(self):
        for code, report in self.reports.items():
            supported = code != 'general_ledger'
            self.assertEqual(report.supports_account_hierarchy, supported)
            self.assertEqual(report.get_default_options().get('hierarchical_groups'), True if supported else None)
            payload = self._render(code, hierarchical_groups=False)
            self.assertEqual(payload['meta']['supports_account_hierarchy'], supported)
            if supported:
                self.assertFalse(payload['meta']['hierarchical_groups'])
                self.assertFalse(self._groups(payload))
                for invalid in ['false', 0, 1, None, []]:
                    with self.subTest(code=code, invalid=invalid), self.assertRaises(UserError):
                        self._render(code, hierarchical_groups=invalid)
            else:
                handler = self.env[report.handler_model]
                self.assertNotIn('hierarchical_groups', handler.normalize_options(self.options))
                self.assertNotIn('hierarchical_groups', payload['meta'])

    def test_saved_flat_and_hierarchy_views_reopen_without_coercion(self):
        Saved = self.env['eh.account.report.saved_view']
        for choice in [False, True]:
            options = dict(self.options, hierarchical_groups=choice, ledger_scope='all')
            view = Saved.browse(Saved.save_view('Parent layout %s' % choice, 'profit_and_loss', options))
            loaded = view.load_options()
            self.assertIs(loaded['hierarchical_groups'], choice)
            payload = self.reports['profit_and_loss'].render(loaded, use_cache=False)
            self.assertEqual(bool(self._groups(payload)), choice)
        with self.assertRaises(ValidationError):
            Saved.save_view('Invalid parent option', 'profit_and_loss', {'hierarchical_groups': 'false'})

    def test_export_layout_and_financial_values_match_interactive_rows(self):
        report = self.reports['profit_and_loss']
        for choice, label in [(True, 'Account hierarchy'), (False, 'Flat accounts')]:
            options = dict(self.options, hierarchical_groups=choice, ledger_scope='all', comparison='previous_year')
            payload = report.render(options, use_cache=False)
            sheet = load_workbook(BytesIO(report.render_xlsx(options, use_cache=False))).active
            rows = list(sheet.values)
            values = [value for row in rows for value in row]
            self.assertTrue(any(isinstance(value, str) and 'Account layout: %s' % label in value for value in values))
            for line in self._groups(payload):
                matches = [row for row in rows if line['name'] in row]
                self.assertTrue(matches, line['name'])
                self.assertIn(line['columns'][0]['value'], matches[0])
            html = report.render_pdf(options)
            if not html.startswith(b'%PDF'):
                self.assertIn(label.encode(), html)
                for line in self._groups(payload):
                    self.assertIn(line['name'].encode(), html)

    def test_hierarchy_rejects_foreign_leaf_and_primary_company(self):
        foreign = self.env['res.company'].create({'name': 'Outside parent report'})
        account = self.env['account.account'].with_company(foreign).create({
            'name': 'Foreign secret', 'code': '99001', 'account_type': 'asset_current',
            'company_ids': [(6, 0, foreign.ids)],
        })
        handler = self.env['eh.account.dynamic.report.handler.sectioned']
        with self.assertRaises(AccessError):
            handler._eh_account_hierarchy(account.ids, self.options)
        with self.assertRaises(AccessError):
            handler._eh_account_hierarchy(self.account_cash.ids, dict(self.options, primary_company_id=foreign.id))

    def test_hidden_ancestor_fails_closed_without_reading_its_label(self):
        user = new_test_user(self.env, login='parent_account_reader', groups='account.group_account_readonly,eh_account_base.group_eh_user')
        hidden = self.chains['income'][0]
        self.env['ir.access'].create({
            'name': 'Restrict parent report ancestor',
            'model_id': self.env['ir.model']._get_id('account.account'),
            'operation': 'r', 'domain': repr([('id', '!=', hidden.id)]),
        })
        handler = self.env['eh.account.dynamic.report.handler.sectioned'].with_user(user)
        self.assertFalse(self.env['account.account'].with_user(user).with_context(active_test=False).search([('id', '=', hidden.id)]))
        with self.assertRaisesRegex(AccessError, 'inaccessible ancestors'):
            handler._eh_account_hierarchy(self.account_revenue.ids, self.options)

    def test_rename_reparent_archive_and_delete_expire_cached_report(self):
        report = self.reports['profit_and_loss']
        first = report.render(self.options)
        self.assertFalse(first['from_cache'])
        self.assertTrue(report.render(self.options)['from_cache'])
        root = self.chains['income'][0]
        root.name = 'Renamed parent after cached report'
        renamed = report.render(self.options)
        self.assertFalse(renamed['from_cache'])
        self.assertIn(root.name, [line['name'] for line in renamed['lines']])
        self.account_revenue.parent_id = root.id
        moved = report.render(self.options)
        self.assertFalse(moved['from_cache'])
        leaf = next(line for line in moved['lines'] if line['id'] == 'account-%s' % self.account_revenue.id)
        root_line = next(line for line in self._groups(moved) if line['meta']['group_id'] == root.id)
        self.assertEqual(leaf['parent_id'], root_line['id'])
        root.active = True
        self.assertFalse(report.render(self.options)['from_cache'])
        spare = self.env['account.account'].create({
            'name': 'Disposable empty parent', 'code': '9899', 'account_type': 'income',
            'company_ids': [(6, 0, self.company.ids)],
        })
        report.render(self.options)
        spare.unlink()
        self.assertFalse(report.render(self.options)['from_cache'])

    def test_cached_hierarchy_rechecks_revoked_account_access(self):
        user = new_test_user(self.env, login='cached_parent_reader', groups='account.group_account_readonly,eh_account_base.group_eh_user')
        report = self.reports['profit_and_loss'].with_user(user)
        report.render(self.options)
        self.assertTrue(report.render(self.options)['from_cache'])
        self.env['ir.access'].create({
            'name': 'Revoke cached parent read',
            'model_id': self.env['ir.model']._get_id('account.account'),
            'operation': 'r',
            'domain': repr([('id', '!=', self.chains['income'][0].id)]),
        })
        with self.assertRaises(AccessError):
            report.render(self.options)

    def test_multiple_companies_keep_separate_parent_identifiers_and_totals(self):
        company = self.env['res.company'].create({
            'name': 'Second parent chart company', 'currency_id': self.company.currency_id.id,
        })
        self.env.user.company_ids |= company
        self.env.user.group_ids |= self.env.ref('eh_account_base.group_eh_manager')
        Account = self.env['account.account'].with_company(company)
        common = {'company_ids': [(6, 0, company.ids)]}
        parent = Account.create(dict(common, name='Second income parent', code='PR2', account_type='income', active=False))
        revenue = Account.create(dict(common, name='Second revenue', code='REV2', account_type='income', parent_id=parent.id))
        cash = Account.create(dict(common, name='Second cash', code='CASH2', account_type='asset_cash'))
        journal = self.env['account.journal'].create({
            'name': 'Second parent journal', 'code': 'PAR2', 'type': 'general', 'company_id': company.id,
        })
        self.post_balanced_move([
            {'account': cash, 'debit': 70}, {'account': revenue, 'credit': 70},
        ], journal=journal, date=fields.Date.to_date('2026-06-15'))
        payload = self._render(company_ids=(self.company | company).ids, primary_company_id=self.company.id)
        self._assert_parent_sums(payload)
        group = next(line for line in self._groups(payload) if line['meta']['group_id'] == parent.id)
        self.assertEqual(group['columns'][0]['value'], 70)
        self.assertEqual(payload['totals']['net_profit'], 200)
        own = self._render()
        self.assertNotIn(parent.id, [line['meta']['group_id'] for line in self._groups(own)])

    def test_registry_support_matrix_is_explicit(self):
        # Support is a property of the handler. Other installed modules may
        # add catalog rows that reuse one of these handlers (a localisation
        # return that links its audit rows to the profit and loss handler),
        # so the matrix is pinned per handler and per shipped report code.
        hierarchy_handlers = {
            'eh.account.dynamic.report.handler.trial_balance',
            'eh.account.dynamic.report.handler.profit_and_loss',
            'eh.account.dynamic.report.handler.balance_sheet',
        }
        self.assertEqual({
            name for name in self.env.registry
            if name.startswith('eh.account.dynamic.report.handler')
            and getattr(self.env[name], '_EH_ACCOUNT_HIERARCHY', False)
        }, hierarchy_handlers)
        reports = self.env['eh.account.dynamic.report'].search([])
        supported = reports.filtered('supports_account_hierarchy')
        self.assertEqual(set(supported.mapped('handler_model')), hierarchy_handlers)
        self.assertLessEqual({'trial_balance', 'profit_and_loss', 'balance_sheet'}, set(supported.mapped('code')))
        for report in reports - supported:
            self.assertNotIn('hierarchical_groups', report.get_default_options())

    def test_flat_layout_enforces_leaf_access_without_exposing_hidden_ancestors(self):
        user = new_test_user(self.env, login='flat_account_reader', groups='account.group_account_readonly,eh_account_base.group_eh_user')
        report = self.reports['profit_and_loss'].with_user(user)
        options = dict(self.options, hierarchical_groups=False)
        report.render(options)
        self.assertTrue(report.render(options)['from_cache'])
        rule = self.env['ir.access'].create({
            'name': 'Hide undisplayed ancestor only',
            'model_id': self.env['ir.model']._get_id('account.account'),
            'operation': 'r',
            'domain': repr([('id', '!=', self.chains['income'][0].id)]),
        })
        self.assertFalse(self._groups(report.render(options)))
        rule.domain = repr([('id', '!=', self.account_revenue.id)])
        for use_cache in [True, False]:
            with self.subTest(use_cache=use_cache), self.assertRaises(AccessError):
                report.render(options, use_cache=use_cache)
