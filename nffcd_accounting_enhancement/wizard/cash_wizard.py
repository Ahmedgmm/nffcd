from odoo import api, Command, fields, models, _
from odoo.exceptions import ValidationError


class PaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    cash_journal_type = fields.Selection(related='journal_id.type')
    cash_fund_id = fields.Many2one('account.cash.fund', string='Cash Classification',
        compute='_compute_cash_fund', readonly=False, store=True, check_company=True)
    cash_split = fields.Boolean(string='Split Amount / توزيع المبلغ')
    cash_allocation_ids = fields.One2many('account.cash.register.allocation', 'wizard_id',
                                         string='Classification Split')

    @api.depends('journal_id')
    def _compute_cash_fund(self):
        for wizard in self:
            if wizard.journal_id.type != 'cash':
                wizard.cash_fund_id = False
            elif wizard.cash_fund_id.journal_id != wizard.journal_id:
                wizard.cash_fund_id = self.env['account.cash.fund'].search([
                    ('journal_id', '=', wizard.journal_id.id), ('is_general', '=', True)], limit=1)

    def _create_payment_vals_from_wizard(self, batch_result):
        vals = super()._create_payment_vals_from_wizard(batch_result)
        vals['cash_fund_id'] = self.cash_fund_id.id
        if self.journal_id.type == 'cash' and self.cash_split:
            vals.update(cash_split=True, cash_allocation_ids=[Command.create({
                'fund_id': a.fund_id.id, 'amount': a.amount}) for a in self.cash_allocation_ids])
        return vals

    def _create_payment_vals_from_batch(self, batch_result):
        if self.cash_split and self.journal_id.type == 'cash':
            raise ValidationError(_('Group the payment first, or split each payment individually.'))
        vals = super()._create_payment_vals_from_batch(batch_result)
        vals['cash_fund_id'] = self.cash_fund_id.id
        return vals


class CashRegisterAllocation(models.TransientModel):
    _name = 'account.cash.register.allocation'
    _description = 'Register Payment Classification Split'
    _check_company_auto = True

    wizard_id = fields.Many2one('account.payment.register', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='wizard_id.company_id')
    currency_id = fields.Many2one(related='wizard_id.currency_id')
    fund_id = fields.Many2one('account.cash.fund', required=True, check_company=True)
    amount = fields.Monetary(required=True)


class CashReclassification(models.TransientModel):
    _name = 'account.cash.reclassification'
    _description = 'Transfer Between Cash Classifications'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    journal_id = fields.Many2one('account.journal', string='Safe', required=True, check_company=True,
                                 domain="[('type', '=', 'cash'), ('company_id', '=', company_id)]")
    source_fund_id = fields.Many2one('account.cash.fund', string='From Classification', required=True, check_company=True)
    destination_fund_id = fields.Many2one('account.cash.fund', string='To Classification', required=True, check_company=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    amount = fields.Monetary(required=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    reason = fields.Char(required=True)

    def action_create(self):
        self.ensure_one()
        if self.amount <= 0 or self.source_fund_id == self.destination_fund_id:
            raise ValidationError(_('Use a positive amount and two different classifications.'))
        if any(f.journal_id != self.journal_id or not f.active for f in self.source_fund_id | self.destination_fund_id):
            raise ValidationError(_('Both classifications must be active and belong to this safe.'))
        if not self.journal_id.default_account_id:
            raise ValidationError(_('Configure the safe cash account first.'))
        move = self.env['account.move'].create({
            'journal_id': self.journal_id.id, 'date': self.date, 'ref': self.reason,
            'line_ids': [Command.create({
                'name': self.reason, 'account_id': self.journal_id.default_account_id.id,
                'debit': self.amount if incoming else 0,
                'credit': 0 if incoming else self.amount,
                'cash_fund_id': fund.id, 'cash_is_transfer': True,
            }) for fund, incoming in [(self.source_fund_id, False), (self.destination_fund_id, True)]],
        })
        # Keep it draft for review and the project's ordinary entry approvals.
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move',
                'res_id': move.id, 'view_mode': 'form'}


class CashStatement(models.TransientModel):
    _name = 'account.cash.statement'
    _description = 'Cash Classification Statement'

    fund_id = fields.Many2one('account.cash.fund', string='Classification', required=True)
    company_id = fields.Many2one(related='fund_id.company_id')
    currency_id = fields.Many2one(related='fund_id.currency_id')
    date_from = fields.Date(required=True, default=lambda self: fields.Date.today().replace(day=1))
    date_to = fields.Date(required=True, default=fields.Date.context_today)

    def _statement_values(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise ValidationError(_('The start date must be before the end date.'))
        report = self.env['account.cash.fund.report']
        domain = [('fund_id', '=', self.fund_id.id)]
        opening = report._read_group(domain + [('date', '<', self.date_from)], [], ['balance:sum'])[0][0]
        movements = report.search(domain + [('date', '>=', self.date_from), ('date', '<=', self.date_to)])
        running = opening
        lines = []
        for movement in movements:
            running += movement.balance
            lines.append({'date': movement.date, 'entry': movement.move_id.name,
                          'reference': movement.reference, 'receipts': movement.receipts,
                          'spending': movement.spending, 'transfers': movement.transfers, 'balance': running})
        return {'opening': opening, 'closing': running, 'lines': lines,
                'receipts': sum(movements.mapped('receipts')), 'spending': sum(movements.mapped('spending')),
                'transfers': sum(movements.mapped('transfers'))}

    def action_print(self):
        self._statement_values()
        return self.env.ref('nffcd_accounting_enhancement.action_cash_statement_pdf').report_action(self)

    def action_movements(self):
        self._statement_values()
        return {'type': 'ir.actions.act_window', 'name': _('Classification Movements'),
                'res_model': 'account.cash.fund.report', 'view_mode': 'list,pivot,graph',
                'domain': [('fund_id', '=', self.fund_id.id), ('date', '>=', self.date_from), ('date', '<=', self.date_to)]}
