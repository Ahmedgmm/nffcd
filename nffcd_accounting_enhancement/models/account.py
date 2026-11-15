from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    cash_journal_id = fields.Many2one('account.journal', string='Safe',
        compute='_compute_cash_journal', store=True, index=True)
    cash_fund_id = fields.Many2one('account.cash.fund', string='Cash Classification',
        compute='_compute_cash_fund', store=True, readonly=False, copy=True,
        check_company=True, ondelete='restrict')
    cash_allocation_ids = fields.One2many('account.cash.move.allocation', 'move_line_id',
                                         string='Classification Split', copy=True)
    cash_is_transfer = fields.Boolean(string='Cash Transfer', copy=True)

    @api.depends('account_id', 'company_id', 'journal_id')
    def _compute_cash_journal(self):
        for line in self:
            journal = line.journal_id
            if journal.type == 'cash' and journal.default_account_id == line.account_id:
                line.cash_journal_id = journal
            else:
                line.cash_journal_id = self.env['account.journal'].with_context(active_test=False).search([
                    ('type', '=', 'cash'), ('default_account_id', '=', line.account_id.id),
                    ('company_id', '=', line.company_id.id)], limit=1) if line.account_id else False

    @api.depends('cash_journal_id')
    def _compute_cash_fund(self):
        for line in self:
            if not line.cash_journal_id:
                line.cash_fund_id = False
            elif line.cash_fund_id.journal_id != line.cash_journal_id:
                line.cash_fund_id = self.env['account.cash.fund'].search([
                    ('journal_id', '=', line.cash_journal_id.id), ('is_general', '=', True)], limit=1)

    def write(self, vals):
        if {'cash_fund_id', 'cash_allocation_ids', 'cash_is_transfer'} & vals.keys():
            if self.filtered(lambda line: line.parent_state == 'posted'):
                raise UserError(_('Posted classifications are locked. Reverse the entry or record a classification transfer.'))
        return super().write(vals)

    def _check_cash_classification(self):
        for line in self:
            if not line.cash_journal_id:
                if line.cash_fund_id or line.cash_allocation_ids:
                    raise ValidationError(_('Only a safe cash-account line can have a classification.'))
                continue
            if line.cash_allocation_ids:
                if any(a.fund_id.journal_id != line.cash_journal_id or not a.fund_id.active
                       or a.amount <= 0 for a in line.cash_allocation_ids):
                    raise ValidationError(_('Use active classifications from this safe and positive split amounts.'))
                if not line.company_currency_id.is_zero(
                    sum(line.cash_allocation_ids.mapped('amount')) - abs(line.balance)):
                    raise ValidationError(_('Classification splits must equal the cash line amount in company currency.'))
            elif not line.cash_fund_id or line.cash_fund_id.journal_id != line.cash_journal_id:
                raise ValidationError(_('Select a classification belonging to this safe.'))
            elif not line.cash_fund_id.active:
                raise ValidationError(_('An archived classification cannot receive new movements.'))


class CashMoveAllocation(models.Model):
    _name = 'account.cash.move.allocation'
    _description = 'Cash Journal Item Classification Split'
    _check_company_auto = True

    move_line_id = fields.Many2one('account.move.line', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='move_line_id.company_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    fund_id = fields.Many2one('account.cash.fund', required=True, ondelete='restrict', check_company=True)
    amount = fields.Monetary(required=True)

    def _check_editable(self):
        if any(a.move_line_id.parent_state == 'posted' for a in self):
            raise UserError(_('Posted classification splits cannot be changed.'))

    @api.model_create_multi
    def create(self, vals_list):
        lines = self.env['account.move.line'].browse([v['move_line_id'] for v in vals_list if v.get('move_line_id')])
        if any(line.parent_state == 'posted' for line in lines):
            raise UserError(_('Posted classification splits cannot be changed.'))
        return super().create(vals_list)

    def write(self, vals):
        self._check_editable()
        if vals.get('move_line_id'):
            if self.env['account.move.line'].browse(vals['move_line_id']).parent_state == 'posted':
                raise UserError(_('Posted classification splits cannot be changed.'))
        return super().write(vals)

    def unlink(self):
        self._check_editable()
        return super().unlink()


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _post(self, soft=True):
        # Lock all affected safes in a stable order. Concurrent spending cannot
        # both pass the same balance check. Reports use this same SQL ledger.
        cash_lines = self.line_ids.filtered('cash_journal_id')
        journal_ids = sorted(cash_lines.cash_journal_id.ids)
        if journal_ids:
            self.env.cr.execute('SELECT id FROM account_journal WHERE id IN %s ORDER BY id FOR UPDATE',
                                [tuple(journal_ids)])
            # Bump the row versions too: Odoo uses repeatable-read isolation,
            # so a waiting concurrent transaction must retry with a fresh
            # snapshot instead of checking an older fund balance.
            self.env.cr.execute('UPDATE account_journal SET write_date = write_date WHERE id IN %s',
                                [tuple(journal_ids)])
        for move in self:
            liquidity = move.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_cash' and l.balance)
            if len(liquidity) > 1 and any(l.balance > 0 for l in liquidity) and any(l.balance < 0 for l in liquidity):
                move.line_ids.filtered('cash_journal_id').cash_is_transfer = True
        cash_lines._check_cash_classification()
        result = super()._post(soft=soft)
        # Check after posting, inside the same transaction, to cover batches,
        # backdated entries and reversal entries with the exact posted amounts.
        funds = cash_lines.cash_fund_id | cash_lines.cash_allocation_ids.fund_id
        guarded = funds.filtered(lambda f: not f.allow_negative)
        guarded.invalidate_recordset(['balance'])
        for fund in guarded:
            if fund.currency_id.compare_amounts(fund.balance, 0) < 0:
                raise ValidationError(_('Insufficient balance in %(safe)s / %(fund)s.',
                                        safe=fund.journal_id.name, fund=fund.name))
        return result
