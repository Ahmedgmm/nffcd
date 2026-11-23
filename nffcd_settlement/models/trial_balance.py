"""Separate eight-measure surface using the standard fiscal and hierarchy engine."""
from odoo import api, models, _
from odoo.exceptions import UserError
from odoo.tools import SQL
from odoo.addons.eh_account_base.tools.sql_builder import MoveLineQuery


class SettlementTrialBalance(models.AbstractModel):
    _name = 'eh.account.dynamic.report.handler.settlement_trial_balance'
    _inherit = 'eh.account.dynamic.report.handler.trial_balance'
    _description = 'Trial Balance with Settlements'
    REPORT_CODE = 'settlement_trial_balance'
    _EH_COLUMN_AXIS_CAPABILITIES = frozenset()
    _EH_ANALYTIC_COLUMN_DRILLDOWN = False

    def _opening_sql(self):
        return SQL("(aj.type != 'settlement' AND COALESCE("
                   "(SELECT lp.purpose='opening' FROM nffcd_legacy_purpose lp WHERE lp.move_id=am.id "
                   "AND lp.company_id=aml.company_id), am.settlement_opening, FALSE))")

    def apply_common_filters(self, query, options):
        super().apply_common_filters(query, options)
        accessible = self.env['account.move.line']._search([])
        query.where_raw(SQL('aml.id IN (%s)', accessible.select()))
        return query

    def _extra_buckets(self, company_ids, date_from, date_to, posted_only, options, currency_table=None):
        query = MoveLineQuery(self.env, company_ids, currency_table=currency_table)
        query.where_date_range(date_from, date_to)
        if posted_only:
            query.where_posted_only()
        self.apply_common_filters(query, options)
        query._joined_tables.add('account_journal')
        query.select_field('account_id').group_by('account_id')
        for key, predicate in [('designated', self._opening_sql()), ('settlement', SQL("aj.type='settlement'"))]:
            for side in ('debit', 'credit'):
                amount = SQL('aml.%s', SQL.identifier(side))
                if currency_table is not None and not currency_table.is_monocurrency:
                    amount = SQL('(%s) * (%s)', amount, currency_table.rate_expr())
                query.select(SQL('SUM(CASE WHEN %s THEN %s ELSE 0 END)', predicate, amount), key + '_' + side)
        return {r['account_id']: r for r in query.execute()}

    def _fetch_account_buckets(self, company_ids, date_from, date_to, posted_only, options, currency_table=None):
        rows = super()._fetch_account_buckets(company_ids, date_from, date_to, posted_only, options, currency_table)
        # A shared Odoo 20 account may have different codes in different
        # root-company contexts. Keep one numeric row per account identity.
        merged = {}
        for row in rows:
            if row['account_id'] in merged:
                for key in ('opening_balance', 'period_debit', 'period_credit'):
                    merged[row['account_id']][key] += row[key] or 0
            else:
                merged[row['account_id']] = dict(row)
        rows = list(merged.values())
        extra = self._extra_buckets(company_ids, date_from, date_to, posted_only, options, currency_table)
        for row in rows:
            values = extra.get(row['account_id'], {})
            debit, credit = (float(values.get('designated_' + side) or 0) for side in ('debit', 'credit'))
            row['opening_balance'] = float(row['opening_balance'] or 0) + debit - credit
            row['period_debit'] = float(row['period_debit'] or 0) - debit
            row['period_credit'] = float(row['period_credit'] or 0) - credit
        return rows

    @api.model
    def compute(self, options):
        if self._extract_date(options, 'date_from') > self._extract_date(options, 'date_to'):
            raise UserError(_('Start date must be on or before end date.'))
        if options.get('comparison') not in (None, 'none') or any(options.get(key) for key in (
                'analytic_account_ids', 'analytic_plan_ids', 'cash_basis',
                'analytic_column_plan_ids', 'analytic_column_account_ids')):
            raise UserError(_('Comparison, cash basis and analytic allocation options are unavailable for this report.'))
        self, options = self._eh_with_ledger_scope(options)
        result = super().compute(options)
        extra = self._extra_buckets(options.get('company_ids') or [self.env.company.id],
                                    self._extract_date(options, 'date_from'), self._extract_date(options, 'date_to'),
                                    options.get('posted_only', True), options,
                                    self._resolve_currency_table(options, options.get('company_ids') or [self.env.company.id]))
        hierarchy = self.env['eh.account.dynamic.report.handler.sectioned']._eh_account_hierarchy(list(extra), options=options)
        group_sums = {}
        for aid, values in extra.items():
            path = hierarchy['ancestors'].get(aid, ())
            if aid in hierarchy['parents']:
                path = path + (aid,)
            for gid in path:
                bucket = group_sums.setdefault(gid, [0., 0.])
                bucket[0] += float(values.get('settlement_debit') or 0)
                bucket[1] += float(values.get('settlement_credit') or 0)
        table = self._resolve_currency_table(options, options.get('company_ids') or [self.env.company.id])
        currency = self._eh_monetary_currency(options=options, company_ids=options.get('company_ids'),
                                            presentation_converted=table is not None and not table.is_monocurrency)
        for line in result['lines']:
            aid = line.get('meta', {}).get('account_id')
            if aid:
                values = extra.get(aid, {})
                sides = [float(values.get('settlement_' + side) or 0) for side in ('debit', 'credit')]
            else:
                sides = group_sums.get(line.get('meta', {}).get('group_id'), [0., 0.])
            cells = {c['expression_label']: c for c in line['columns']}
            for side, value in zip(('debit', 'credit'), sides):
                cells['period_' + side]['value'] = self._eh_round_monetary(cells['period_' + side]['value'] - value, currency=currency)
            line['columns'][4:4] = [{'expression_label': 'settlement_' + side,
                                     'value': self._eh_round_monetary(value, currency=currency)}
                                    for side, value in zip(('debit', 'credit'), sides)]
        for side in ('debit', 'credit'):
            value = sum(float(r.get('settlement_' + side) or 0) for r in extra.values())
            result['totals']['period_' + side] = self._eh_round_monetary(result['totals']['period_' + side] - value, currency=currency)
            result['totals']['settlement_' + side] = self._eh_round_monetary(value, currency=currency)
        result['column_header_rows'] = [[{'name': _('Account'), 'colspan': 1, 'rowspan': 2},
            *[{'name': name, 'colspan': 2} for name in (_('Opening Balance'), _('Current-period Financial Movements'), _('Current-period Settlements'), _('Ending Balance'))]],
            [{'name': label, 'colspan': 1} for i in range(4) for label in (_('Debit'), _('Credit'))]]
        result['meta']['classification_rule'] = 'settlement_journal_only'
        return result

    def _build_columns(self, comparison=False):
        return [{'expression_label': 'account', 'name': _('Account'), 'figure_type': 'string'}] + [
            {'expression_label': section + '_' + side, 'name': '%s — %s' % (name, label), 'figure_type': 'monetary'}
            for section, name in [('opening', _('Opening Balance')), ('period', _('Current-period Financial Movements')),
                                  ('settlement', _('Current-period Settlements')), ('closing', _('Ending Balance'))]
            for side, label in [('debit', _('Debit')), ('credit', _('Credit'))]]

    @api.model
    def get_drilldown_action(self, options, line_id):
        self, options = self._eh_with_ledger_scope(options)
        expression = options.get('_eh_column_expression', '')
        if expression not in {s + '_' + d for s in ('opening', 'period', 'settlement', 'closing') for d in ('debit', 'credit')}:
            return None
        domain = []
        synthetic = line_id == 'account-unaffected-earnings'
        try:
            if line_id.startswith('account-') and not synthetic:
                domain = [('id', '=', int(line_id[8:]))]
            elif line_id.startswith('section-trial_balance-group-'):
                domain = [('id', 'child_of', int(line_id.rsplit('-', 1)[1].split('_')[-1]))]
            elif line_id != 'settlement-total' and not synthetic:
                return None
        except (ValueError, AttributeError):
            return None
        if options.get('account_ids'):
            domain.append(('id', 'in', options['account_ids']))
        if options.get('account_type_ids'):
            domain.append(('account_type', 'in', options['account_type_ids']))
        accounts = self.env['account.account'].with_context(active_test=False).search(domain)
        selected = [] if synthetic else accounts.ids
        if (synthetic or line_id == 'settlement-total') and not options.get('account_ids') and not options.get('account_type_ids'):
            selected.append(0)  # the standard engine's unallocated earnings row
        companies = options.get('company_ids') or [self.env.company.id]
        start, end = self._extract_date(options, 'date_from'), self._extract_date(options, 'date_to')
        query = MoveLineQuery(self.env, companies)
        query._joined_tables.add('account_journal')
        section, side = expression.rsplit('_', 1)
        query.where_date_range(date_to=end)
        scope_options = dict(options)
        destinations = self.env['eh.account.dynamic.report.handler.general_ledger']._unaffected_account_ids(companies)
        query.join_account()
        fy = self._fiscalyear_start_case(self._fiscalyear_starts(companies, start), start)
        destination_case = SQL('CASE aml.company_id %s ELSE 0 END', SQL(' ').join(
            SQL('WHEN %s THEN %s', cid, destination) for cid, destination in destinations.items())) if destinations else SQL('0')
        report_account = SQL('CASE WHEN (acc.account_type LIKE %s OR acc.account_type LIKE %s) '
                             'AND aml.date < (%s) THEN (%s) ELSE aml.account_id END',
                             'income%', 'expense%', fy, destination_case)
        query.where_raw(SQL('(%s) IN %s', report_account, tuple(selected) or (-1,)))
        scope_options.pop('account_ids', None)
        scope_options.pop('account_type_ids', None)
        if options.get('posted_only', True):
            query.where_posted_only()
        self.apply_common_filters(query, scope_options)
        opening = self._opening_sql()
        if section == 'opening':
            query.where_raw(SQL('(aml.date < %s OR (aml.date >= %s AND %s))', start, start, opening))
        elif section in ('period', 'settlement'):
            query.where_date_range(date_from=start)
            query.where_raw(SQL("aj.type='settlement'") if section == 'settlement' else SQL("aj.type!='settlement' AND NOT %s", opening))
            query.where_raw(SQL('aml.%s != 0', SQL.identifier(side)))
        query.select_field('id')
        query.select(report_account, 'report_account')
        amount = SQL('aml.balance')
        table = self._resolve_currency_table(options, companies)
        if table is not None and not table.is_monocurrency:
            query.currency_table = table
            amount = SQL('aml.balance * (%s)', table.rate_expr())
        query.select(amount, 'signed_amount')
        rows = query.execute()
        if section in ('opening', 'closing'):
            nets = {}
            for row in rows:
                key = row['report_account']
                nets[key] = nets.get(key, 0) + float(row['signed_amount'] or 0)
            rows = [row for row in rows if (nets[row['report_account']] > 0 if side == 'debit' else nets[row['report_account']] < 0)]
        ids = [r['id'] for r in rows]
        return {'type': 'ir.actions.act_window', 'name': _('Contributing Journal Items'),
                'res_model': 'account.move.line', 'view_mode': 'list,form',
                'views': [(False, 'list'), (False, 'form')],
                'domain': [('id', 'in', ids)], 'context': {'create': False}}
