from odoo import api, fields, models, _
from odoo.tools import SQL
from odoo.exceptions import UserError, ValidationError


class CashFund(models.Model):
    _name = 'account.cash.fund'
    _description = 'Cash Classification'
    _order = 'journal_id, sequence, name, id'
    _check_company_auto = True

    name = fields.Char(required=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    journal_id = fields.Many2one('account.journal', string='Safe', required=True,
                                 ondelete='restrict', check_company=True,
                                 domain="[('type', '=', 'cash')]")
    company_id = fields.Many2one(related='journal_id.company_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    is_general = fields.Boolean(readonly=True, copy=False)
    # compute_sql lets list group headers (e.g. per safe) total these values.
    balance = fields.Monetary(compute='_compute_balance', compute_sql='_compute_sql_balance',
                              compute_sudo=True, string='Remaining Balance')
    receipts = fields.Monetary(compute='_compute_balance', compute_sql='_compute_sql_receipts',
                               compute_sudo=True)
    spending = fields.Monetary(compute='_compute_balance', compute_sql='_compute_sql_spending',
                               compute_sudo=True)
    transfers = fields.Monetary(compute='_compute_balance', compute_sql='_compute_sql_transfers',
                                compute_sudo=True, string='Net Transfers')

    _name_unique = models.Constraint('unique(journal_id, name)', 'This classification already exists in this safe.')

    def init(self):
        self.env.cr.execute('CREATE UNIQUE INDEX IF NOT EXISTS cash_fund_one_general '
                            'ON account_cash_fund (journal_id) WHERE is_general')

    @api.constrains('journal_id')
    def _check_safe(self):
        if any(fund.journal_id.type != 'cash' for fund in self):
            raise ValidationError(_('Classifications belong to cash journals only.'))

    def _compute_balance(self):
        self.env['account.move'].flush_model(['state'])
        self.env['account.move.line'].flush_model([
            'move_id', 'date', 'balance', 'company_id', 'partner_id', 'name',
            'cash_journal_id', 'cash_fund_id', 'cash_is_transfer'])
        self.env['account.cash.move.allocation'].flush_model()
        # Filter on the indexed safe first so PostgreSQL does not scan every
        # cash line before evaluating the classification expression.
        rows = self.env['account.cash.fund.report']._read_group(
            [('journal_id', 'in', self.journal_id.ids), ('fund_id', 'in', self.ids)], ['fund_id'],
            ['balance:sum', 'receipts:sum', 'spending:sum', 'transfers:sum'])
        totals = {fund.id: values for fund, *values in rows}
        for fund in self:
            fund.balance, fund.receipts, fund.spending, fund.transfers = totals.get(fund.id, [0.0] * 4)

    def _cash_report_sum_sql(self, table, column):
        return SQL(
            "(SELECT COALESCE(SUM(r.%(column)s), 0) FROM account_cash_fund_report r"
            " WHERE r.journal_id = %(journal)s AND r.fund_id = %(fund)s)",
            column=SQL.identifier(column), journal=table.journal_id, fund=table.id)

    def _compute_sql_balance(self, table):
        return self._cash_report_sum_sql(table, 'balance')

    def _compute_sql_receipts(self, table):
        return self._cash_report_sum_sql(table, 'receipts')

    def _compute_sql_spending(self, table):
        return self._cash_report_sum_sql(table, 'spending')

    def _compute_sql_transfers(self, table):
        return self._cash_report_sum_sql(table, 'transfers')

    def write(self, vals):
        if 'is_general' in vals:
            raise UserError(_('The General classification is managed automatically.'))
        if vals.get('active') is False and self.filtered('is_general'):
            raise UserError(_('The General classification must remain active.'))
        if 'journal_id' in vals and any(f.journal_id.id != vals['journal_id'] for f in self):
            raise UserError(_('Create a new classification to use a different safe.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered('is_general'):
            raise UserError(_('The General classification cannot be deleted.'))
        return super().unlink()

    def action_movements(self):
        return {'type': 'ir.actions.act_window', 'name': _('Classification Movements'),
                'res_model': 'account.cash.fund.report', 'view_mode': 'list,pivot,graph',
                'domain': [('fund_id', 'in', self.ids)], 'context': {'create': False}}

    def action_statement(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Classification Statement'),
                'res_model': 'account.cash.statement', 'view_mode': 'form', 'target': 'new',
                'context': {'default_fund_id': self.id}}


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    cash_fund_ids = fields.One2many('account.cash.fund', 'journal_id', string='Cash Classifications')

    @api.constrains('type', 'default_account_id', 'company_id')
    def _check_cash_account_unique(self):
        for journal in self.filtered(lambda j: j.type == 'cash' and j.default_account_id):
            if self.with_context(active_test=False).search_count([
                ('type', '=', 'cash'), ('default_account_id', '=', journal.default_account_id.id),
                ('company_id', '=', journal.company_id.id), ('id', '!=', journal.id)]):
                raise ValidationError(_('Each safe must have its own cash account for reliable classification balances.'))

    @api.model
    def _cash_safe_map(self, account_ids):
        """Map (cash account id, company id) -> safe journal record."""
        if not account_ids:
            return {}
        journals = self.sudo().with_context(active_test=False).search([
            ('type', '=', 'cash'), ('default_account_id', 'in', list(account_ids))], order='id')
        safes = {}
        for journal in journals:
            safes.setdefault((journal.default_account_id.id, journal.company_id.id),
                             self.browse(journal.id))
        return safes

    @api.model
    def _check_cash_accounts_not_shared(self):
        """Fail loudly if two safes share one cash account (legacy data)."""
        self.env.cr.execute("""
            SELECT string_agg(name->>'en_US', ', ' ORDER BY id)
              FROM account_journal
             WHERE type = 'cash' AND default_account_id IS NOT NULL
             GROUP BY company_id, default_account_id
            HAVING count(*) > 1
        """)
        shared = [row[0] for row in self.env.cr.fetchall()]
        if shared:
            raise UserError(_('These safes share one cash account; give each its own account first: %s',
                              '; '.join(shared)))

    def _cash_refresh_lines(self, account_ids):
        """Re-link journal items after a safe's cash account appears or changes."""
        account_ids = [a for a in account_ids if a]
        if not account_ids:
            return
        lines = self.env['account.move.line'].sudo().search([('account_id', 'in', account_ids)])
        if lines:
            Line = self.env['account.move.line']
            self.env.add_to_compute(Line._fields['cash_journal_id'], lines)
            self.env.add_to_compute(Line._fields['cash_fund_id'], lines)
            lines.flush_recordset(['cash_journal_id', 'cash_fund_id'])

    def _ensure_general_cash_fund(self):
        for journal in self.filtered(lambda j: j.type == 'cash'):
            if not self.env['account.cash.fund'].sudo().with_context(active_test=False).search_count([
                ('journal_id', '=', journal.id), ('is_general', '=', True)
            ]):
                self.env['account.cash.fund'].sudo().create({
                    'name': 'عام', 'journal_id': journal.id, 'is_general': True, 'sequence': 0})

    @api.model_create_multi
    def create(self, vals_list):
        journals = super().create(vals_list)
        journals._ensure_general_cash_fund()
        cash = journals.filtered(lambda j: j.type == 'cash')
        cash._cash_refresh_lines(cash.default_account_id.ids)
        return journals

    def write(self, vals):
        if {'default_account_id', 'type', 'company_id'} & vals.keys():
            for journal in self.filtered(lambda j: j.type == 'cash'):
                if any(vals[key] != journal[key].id if key != 'type' else vals[key] != journal.type
                       for key in {'default_account_id', 'type', 'company_id'} & vals.keys()):
                    if self.env['account.move.line'].sudo().search_count([
                        ('account_id', '=', journal.default_account_id.id), ('parent_state', '=', 'posted')]):
                        raise UserError(_('A safe with posted movements must keep its account and company.'))
        relink = {'default_account_id', 'type', 'company_id'} & vals.keys()
        old_accounts = self.filtered(lambda j: j.type == 'cash').default_account_id.ids if relink else []
        result = super().write(vals)
        if vals.get('type') == 'cash':
            self._ensure_general_cash_fund()
        if relink:
            new_accounts = self.filtered(lambda j: j.type == 'cash').default_account_id.ids
            self._cash_refresh_lines(set(old_accounts) | set(new_accounts))
        return result
