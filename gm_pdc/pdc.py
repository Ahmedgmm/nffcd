from odoo import models, fields, api, Command, _
from odoo.exceptions import UserError

class AccountJournal(models.Model):
    _inherit = "account.journal"

    pdc_registered_active = fields.Boolean("Create Entry on Register?")
    pdc_registered_account_id = fields.Many2one('account.account', check_company=True, string="Receivable Registered Account")
    pdc_payable_registered_account_id = fields.Many2one('account.account', check_company=True, string="Payable Registered Account")
    pdc_deposited_active = fields.Boolean("Create Entry on Deposit?")
    pdc_deposited_account_id = fields.Many2one('account.account', check_company=True, string="Receivable Deposited Account")
    pdc_payable_deposited_account_id = fields.Many2one('account.account', check_company=True, string="Payable Deposited Account")
    pdc_bounced_active = fields.Boolean("Create Entry on Bounce?")
    pdc_bounced_account_id = fields.Many2one('account.account', check_company=True, string="Receivable Bounced Account")
    pdc_payable_bounced_account_id = fields.Many2one('account.account', check_company=True, string="Payable Bounced Account")
    pdc_done_active = fields.Boolean("Create Entry on Done?")
    pdc_done_account_id = fields.Many2one('account.account', check_company=True, string="Receivable Done (Bank) Account")
    pdc_payable_done_account_id = fields.Many2one('account.account', check_company=True, string="Payable Done (Bank) Account")

    def _get_pdc_stage_account(self, stage, payment_type):
        self.ensure_one()
        field_by_stage = {
            'registered': 'pdc_registered_account_id',
            'deposited': 'pdc_deposited_account_id',
            'bounced': 'pdc_bounced_account_id',
            'done': 'pdc_done_account_id',
        }
        field_name = field_by_stage[stage]
        if payment_type == 'outbound':
            payable_field_name = 'pdc_payable_%s_account_id' % stage
            return self[payable_field_name] or self[field_name]
        return self[field_name]


class AccountPayment(models.Model):
    _inherit = "account.payment"
    pdc_id = fields.Many2one('account.pdc', string="Related PDC", readonly=True)


class AccountMove(models.Model):
    _inherit = "account.move"

    # Open a PDC only for payable customer/vendor invoices.
    def action_register_pdc(self):
        self.ensure_one()
        if self.move_type not in ('out_invoice', 'in_invoice') or self.state != 'posted' or self.amount_residual <= 0:
            raise UserError(_('Register PDC requires an unpaid posted invoice or bill.'))
        return {
            'name': _('Register PDC'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.pdc',
            'view_mode': 'form',
            'target': 'new', 
            'context': {
                'default_company_id': self.company_id.id,
                'default_partner_id': self.partner_id.id,
                'default_amount': self.amount_residual,
                'default_currency_id': self.currency_id.id,
                'default_memo': self.name,
                'default_payment_type': 'inbound' if self.move_type == 'out_invoice' else 'outbound',
                'default_invoice_ids': [self.id], 
            }
        }

    # Keep uncleared cheques in payment until the PDC completes.
    @api.depends('reconciled_payment_ids.pdc_id.state')
    def _compute_payment_state(self):
        super()._compute_payment_state()
        for move in self:
            if move.payment_state in ('paid', 'in_payment'):
                payments = move._get_reconciled_payments()
                if any(p.pdc_id and p.pdc_id.state != 'done' for p in payments):
                    move.payment_state = 'in_payment'
                elif payments and all((p.pdc_id and p.pdc_id.state == 'done') or p.is_matched for p in payments) and move.currency_id.is_zero(move.amount_residual):
                    move.payment_state = 'paid'



class AccountPDC(models.Model):
    _name = "account.pdc"
    _description = "PDC Cheque Payment"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True
    _order = "date desc, name desc"

    name = fields.Char(string="Name", required=True, copy=False, readonly=True, default=lambda self: _('New'))
    state = fields.Selection([
        ('draft', 'Draft'),
        ('registered', 'Registered'),
        ('returned', 'Returned'),
        ('deposited', 'Deposited'),
        ('under_collection', 'Under Collection'),
        ('bounced', 'Bounced'),
        ('legal', 'Legal'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled')
    ], string="Status", default='draft', tracking=True)

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)

    payment_type = fields.Selection([('inbound', 'Receive Money'), ('outbound', 'Send Money')], 
                                    default='inbound', string="Payment Type", required=True)
    partner_id = fields.Many2one('res.partner', string="Partner", required=True)
    amount = fields.Monetary(string="Payment Amount", required=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', required=True, default=lambda self: self.env.company.currency_id)
    ref = fields.Char(string="Cheque Reference")
    journal_id = fields.Many2one('account.journal', string="Payment Journal", check_company=True, domain=[('type', 'in', ('bank', 'cash'))], required=True)
    date = fields.Date(string="Payment Date", default=fields.Date.context_today)
    due_date = fields.Date(string="Due Date")
    done_date = fields.Date(string="Done Date", readonly=True)
    collect_date = fields.Date(string="Collect Date")
    memo = fields.Char(string="Memo")
    agent = fields.Char(string="Agent")
    bank_name = fields.Char(string="Bank")
    collect_user_id = fields.Many2one('res.users', string="Collect User")

    payment_id = fields.Many2one('account.payment', string="Odoo Payment", readonly=True)
    
    move_ids = fields.Many2many('account.move', string="Journal Entries", readonly=True)
    
    move_count = fields.Integer(compute='_compute_move_count')

    @api.depends('move_ids')
    def _compute_move_count(self):
        for pdc in self:
            pdc.move_count = len(pdc.move_ids)

    holding_account_id = fields.Many2one('account.account', string="Current Holding Account", readonly=True)
    
    invoice_ids = fields.Many2many(
        'account.move', 
        'account_pdc_invoice_rel', 
        'pdc_id', 
        'invoice_id', 
        string="Linked Invoices", check_company=True
    )

    @api.constrains('amount')
    def _check_amount(self):
        if any(pdc.amount <= 0 for pdc in self):
            raise UserError(_('Amount must be greater than zero.'))

    def _check_state(self, allowed):
        self.ensure_one()
        if self.state not in allowed:
            raise UserError(_('This action is not allowed in the current PDC state.'))

    def write(self, vals):
        financial_fields = {'company_id', 'partner_id', 'amount', 'currency_id', 'journal_id', 'payment_type', 'invoice_ids', 'date'}
        if financial_fields.intersection(vals) and any(pdc.state != 'draft' for pdc in self):
            raise UserError(_('Reset the PDC to draft before changing its financial details.'))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft(self):
        if any(pdc.state != 'draft' or pdc.move_ids for pdc in self):
            raise UserError(_('Only draft PDCs without journal entries can be deleted.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('account.pdc') or _('New')
        return super().create(vals_list)

    def action_view_journal_items(self):
        self.ensure_one()
        return {
            'name': _('Journal Entries'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.move_ids.ids)],
            'context': {'create': False},
        }

    # --- ACTION REGISTER ---
    def action_register(self):
        self.ensure_one()
        self._check_state(('draft',))
        self = self.with_company(self.company_id)
        expected_type = 'out_invoice' if self.payment_type == 'inbound' else 'in_invoice'
        if any(inv.company_id != self.company_id or inv.commercial_partner_id != self.partner_id.commercial_partner_id or inv.currency_id != self.currency_id or inv.move_type != expected_type or inv.state != 'posted' for inv in self.invoice_ids):
            raise UserError(_('Linked invoices must match the PDC company, partner, currency and payment direction and be posted.'))
        if self.journal_id.pdc_registered_active:
            if self.amount <= 0:
                raise UserError(_("Amount must be greater than zero."))

            method_type = 'inbound' if self.payment_type == 'inbound' else 'outbound'
            payment_method_line = (
                self.journal_id.inbound_payment_method_line_ids[:1]
                if method_type == 'inbound'
                else self.journal_id.outbound_payment_method_line_ids[:1]
            )

            if not payment_method_line:
                raise UserError(_("Journal '%s' needs a Payment Method configured.") % self.journal_id.name)

            registered_account = self.journal_id._get_pdc_stage_account('registered', self.payment_type)
            if not registered_account:
                raise UserError(_("Journal '%s' needs a Registered PDC account configured.") % self.journal_id.name)

            # Create Standard Payment
            payment_vals = {
                'company_id': self.company_id.id,
                'partner_id': self.partner_id.id,
                'amount': self.amount,
                'date': self.date,
                'memo': self.memo,
                'journal_id': self.journal_id.id,
                'payment_type': self.payment_type,
                'partner_type': 'customer' if self.payment_type == 'inbound' else 'supplier',
                'payment_method_line_id': payment_method_line.id,
                'outstanding_account_id': registered_account.id,
                'currency_id': self.currency_id.id,
            }

            payment = self.env['account.payment'].create(payment_vals)
            if payment.outstanding_account_id != registered_account:
                payment.outstanding_account_id = registered_account.id
            payment.write({'pdc_id': self.id})
            payment.action_post()

            if not payment.move_id:
                if not payment.outstanding_account_id:
                    payment.outstanding_account_id = registered_account.id
                payment._generate_journal_entry()
                payment.move_id.filtered(lambda move: move.state == 'draft').action_post()

            if not payment.move_id:
                raise UserError(_("Odoo did not create a journal entry for payment '%s'. Check the payment method outstanding account.") % payment.display_name)

            payment.move_id.write({'ref': f"{self.name} - {self.ref}"})

            # Reconcile each account separately; invoice accounts may differ from partner defaults.
            for account in self.invoice_ids.line_ids.account_id.filtered(lambda a: a.account_type in ('asset_receivable', 'liability_payable')):
                lines = (payment.move_id.line_ids + self.invoice_ids.line_ids).filtered(
                    lambda line: line.account_id == account and not line.reconciled
                )
                if len(lines) > 1:
                    lines.reconcile()

            self.write({
                'state': 'registered',
                'payment_id': payment.id,
                'move_ids': [Command.link(payment.move_id.id)],
                'holding_account_id': registered_account.id
            })
        else:
            self.write({'state': 'registered'})

    def _create_move(self, target_state, target_account_id, journal_config_active):
        self.ensure_one()
        if journal_config_active and not target_account_id:
            raise UserError(_('Configure the PDC account for this stage before continuing.'))
        if not journal_config_active:
            self.write({'state': target_state})
            return

        stage_label = dict(self._fields['state']._description_selection(self.env))[target_state]
        source_account = self.holding_account_id
        if not source_account:
            raise UserError(_("PDC '%s' has no current holding account. Register it before moving to %s.") % (self.name, stage_label))

        source_account_id = source_account.id
        dest_account_id = target_account_id.id
        company = self.journal_id.company_id or self.env.company
        balance_amount = self.currency_id._convert(
            self.amount,
            company.currency_id,
            company,
            fields.Date.context_today(self),
        )

        debit_account = dest_account_id if self.payment_type == 'inbound' else source_account_id
        credit_account = source_account_id if self.payment_type == 'inbound' else dest_account_id

        move_vals = {
            'ref': f'{self.name} - {stage_label}',
            'date': fields.Date.context_today(self),
            'journal_id': self.journal_id.id,
            'currency_id': self.currency_id.id,
            'move_type': 'entry',
            'line_ids': [
                Command.create({
                    'name': self.memo or self.name,
                    'account_id': debit_account,
                    'debit': balance_amount,
                    'credit': 0.0,
                    'partner_id': self.partner_id.id,
                    'currency_id': self.currency_id.id,
                    'amount_currency': self.amount,
                }),
                Command.create({
                    'name': self.memo or self.name,
                    'account_id': credit_account,
                    'debit': 0.0,
                    'credit': balance_amount,
                    'partner_id': self.partner_id.id,
                    'currency_id': self.currency_id.id,
                    'amount_currency': -self.amount,
                }),
            ]
        }

        move = self.env['account.move'].create(move_vals)
        move.action_post()

        if source_account.reconcile:
            lines = (self.move_ids | move).filtered(lambda entry: entry.state == 'posted').line_ids.filtered(lambda line: line.account_id == source_account and not line.reconciled)
            if len(lines) > 1:
                lines.reconcile()

        self.write({
            'state': target_state,
            'holding_account_id': dest_account_id,
            'move_ids': [Command.link(move.id)]
        })

    def action_deposit(self):
        self._check_state(('registered',))
        self._create_move('deposited', self.journal_id._get_pdc_stage_account('deposited', self.payment_type), self.journal_id.pdc_deposited_active)

    def action_bounce(self):
        self._check_state(('deposited', 'under_collection'))
        self._create_move('bounced', self.journal_id._get_pdc_stage_account('bounced', self.payment_type), self.journal_id.pdc_bounced_active)

    def action_done(self):
        self._check_state(('deposited',))
        self._create_move('done', self.journal_id._get_pdc_stage_account('done', self.payment_type), self.journal_id.pdc_done_active)
        self.write({'done_date': fields.Date.context_today(self)})
        (self.payment_id.reconciled_invoice_ids | self.payment_id.reconciled_bill_ids)._compute_payment_state()

    def action_cancel(self):
        self.ensure_one()
        if self.state == 'done':
            raise UserError(_('A completed PDC cannot be cancelled. Reverse its accounting entries through accounting.'))
        self.move_ids.line_ids.remove_move_reconcile()
        if self.payment_id:
            self.payment_id.action_cancel()
        for move in self.move_ids.filtered(lambda m: m.state != 'cancel'):
            if move.state == 'posted':
                move.button_draft()
            move.button_cancel()
        self.write({'state': 'cancelled', 'holding_account_id': False})

    def action_draft(self):
        self._check_state(('cancelled',))
        self.write({'state': 'draft', 'payment_id': False, 'done_date': False})
