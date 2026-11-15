from odoo import api, fields, models, _
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
    allow_negative = fields.Boolean(string='Allow Negative Balance', default=True)
    balance = fields.Monetary(compute='_compute_balance', string='Remaining Balance')
    receipts = fields.Monetary(compute='_compute_balance')
    spending = fields.Monetary(compute='_compute_balance')
    transfers = fields.Monetary(compute='_compute_balance', string='Net Transfers')

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
        self.env['account.move.line'].flush_model()
        self.env['account.cash.move.allocation'].flush_model()
        rows = self.env['account.cash.fund.report']._read_group(
            [('fund_id', 'in', self.ids)], ['fund_id'],
            ['balance:sum', 'receipts:sum', 'spending:sum', 'transfers:sum'])
        totals = {fund.id: values for fund, *values in rows}
        for fund in self:
            fund.balance, fund.receipts, fund.spending, fund.transfers = totals.get(fund.id, [0.0] * 4)

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
        return journals

    def write(self, vals):
        if {'default_account_id', 'type', 'company_id'} & vals.keys():
            for journal in self.filtered(lambda j: j.type == 'cash'):
                if any(vals[key] != journal[key].id if key != 'type' else vals[key] != journal.type
                       for key in {'default_account_id', 'type', 'company_id'} & vals.keys()):
                    if self.env['account.move.line'].sudo().search_count([
                        ('account_id', '=', journal.default_account_id.id), ('parent_state', '=', 'posted')]):
                        raise UserError(_('A safe with posted movements must keep its account and company.'))
        result = super().write(vals)
        if vals.get('type') == 'cash':
            self._ensure_general_cash_fund()
        return result
