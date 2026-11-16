from odoo import api, Command, fields, models, _
from odoo.exceptions import UserError, ValidationError


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    cash_is_internal_transfer = fields.Boolean(string='Internal Transfer', copy=False)
    cash_operation = fields.Selection([
        ('inbound', 'Receive'), ('outbound', 'Send'), ('transfer', 'Internal Transfer')],
        string='Payment Operation', compute='_compute_cash_operation', inverse='_inverse_cash_operation')
    cash_journal_type = fields.Selection(related='journal_id.type', string='Safe Journal Type')
    cash_fund_id = fields.Many2one('account.cash.fund', string='Cash Classification',
        compute='_compute_cash_fund', store=True, readonly=False, check_company=True,
        ondelete='restrict', tracking=True)
    cash_split = fields.Boolean(string='Split Amount', tracking=True)
    cash_allocation_ids = fields.One2many('account.cash.payment.allocation', 'payment_id',
                                         string='Classification Split', copy=True)
    cash_destination_journal_id = fields.Many2one('account.journal', string='Destination Safe / Bank',
        check_company=True, ondelete='restrict', tracking=True)
    cash_destination_type = fields.Selection(related='cash_destination_journal_id.type',
                                             string='Destination Journal Type')
    cash_destination_fund_id = fields.Many2one('account.cash.fund', string='Destination Classification',
        compute='_compute_destination_fund', store=True, readonly=False,
        check_company=True, ondelete='restrict', tracking=True)
    cash_destination_split = fields.Boolean(string='Split Destination Amount')
    cash_destination_allocation_ids = fields.One2many('account.cash.payment.allocation',
        'destination_payment_id', string='Destination Split', copy=True)
    cash_fund_balance = fields.Monetary(related='cash_fund_id.balance', currency_field='company_currency_id',
                                       string='Classification Balance')
    cash_split_remaining = fields.Monetary(compute='_compute_cash_split_remaining', string='Remaining to Allocate')
    cash_split_balanced = fields.Boolean(compute='_compute_cash_split_remaining')
    cash_destination_split_remaining = fields.Monetary(compute='_compute_cash_split_remaining',
                                                       string='Destination Remaining to Allocate')
    cash_destination_split_balanced = fields.Boolean(compute='_compute_cash_split_remaining')

    @api.depends('amount', 'currency_id', 'cash_allocation_ids.amount', 'cash_destination_allocation_ids.amount')
    def _compute_cash_split_remaining(self):
        for payment in self:
            currency = payment.currency_id or payment.company_currency_id
            remaining = currency.round(payment.amount - sum(payment.cash_allocation_ids.mapped('amount')))
            dest_remaining = currency.round(payment.amount - sum(payment.cash_destination_allocation_ids.mapped('amount')))
            payment.cash_split_remaining = remaining
            payment.cash_split_balanced = currency.is_zero(remaining)
            payment.cash_destination_split_remaining = dest_remaining
            payment.cash_destination_split_balanced = currency.is_zero(dest_remaining)

    @api.depends('payment_type', 'cash_is_internal_transfer')
    def _compute_cash_operation(self):
        for payment in self:
            payment.cash_operation = 'transfer' if payment.cash_is_internal_transfer else payment.payment_type

    def _inverse_cash_operation(self):
        for payment in self:
            operation = payment.cash_operation
            payment.cash_is_internal_transfer = operation == 'transfer'
            payment.payment_type = 'outbound' if operation == 'transfer' else operation

    @api.onchange('cash_operation')
    def _onchange_cash_operation(self):
        self._inverse_cash_operation()
        if self.cash_is_internal_transfer:
            self.partner_id = False

    @api.depends('journal_id')
    def _compute_cash_fund(self):
        for payment in self:
            if payment.journal_id.type != 'cash':
                payment.cash_fund_id = False
            elif payment.cash_fund_id.journal_id != payment.journal_id:
                payment.cash_fund_id = self.env['account.cash.fund'].search([
                    ('journal_id', '=', payment.journal_id.id), ('is_general', '=', True)], limit=1)

    @api.depends('cash_destination_journal_id')
    def _compute_destination_fund(self):
        for payment in self:
            journal = payment.cash_destination_journal_id
            if journal.type != 'cash':
                payment.cash_destination_fund_id = False
            elif payment.cash_destination_fund_id.journal_id != journal:
                payment.cash_destination_fund_id = self.env['account.cash.fund'].search([
                    ('journal_id', '=', journal.id), ('is_general', '=', True)], limit=1)

    @api.onchange('journal_id')
    def _onchange_cash_journal(self):
        self.cash_split = False
        self.cash_allocation_ids = [Command.clear()]

    @api.onchange('cash_split')
    def _onchange_cash_split(self):
        # Seed the split with the current classification so the user only
        # has to adjust amounts rather than start from an empty table.
        if self.cash_split and not self.cash_allocation_ids and self.cash_fund_id:
            self.cash_allocation_ids = [Command.create({'fund_id': self.cash_fund_id.id, 'amount': self.amount})]

    @api.onchange('cash_destination_split')
    def _onchange_cash_destination_split(self):
        if self.cash_destination_split and not self.cash_destination_allocation_ids and self.cash_destination_fund_id:
            self.cash_destination_allocation_ids = [Command.create({
                'fund_id': self.cash_destination_fund_id.id, 'amount': self.amount})]

    @api.onchange('cash_destination_journal_id')
    def _onchange_cash_destination(self):
        self.cash_destination_split = False
        self.cash_destination_allocation_ids = [Command.clear()]

    @api.depends('journal_id', 'partner_id', 'partner_type', 'cash_is_internal_transfer')
    def _compute_destination_account_id(self):
        super()._compute_destination_account_id()
        for payment in self.filtered('cash_is_internal_transfer'):
            payment.destination_account_id = payment.company_id.transfer_account_id

    @api.depends('payment_method_line_id', 'journal_id')
    def _compute_outstanding_account_id(self):
        super()._compute_outstanding_account_id()
        # Cash payments hit the safe immediately. Bank journals keep their
        # standard outstanding/reconciliation configuration.
        for payment in self.filtered(lambda p: p.journal_id.type == 'cash'):
            payment.outstanding_account_id = payment.journal_id.default_account_id

    def _get_outstanding_account(self, payment_type):
        if self.journal_id.type == 'cash' and self.journal_id.default_account_id:
            return self.journal_id.default_account_id
        return super()._get_outstanding_account(payment_type)

    def action_toggle_cash_split(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only draft payments can be split.'))
        if not self.cash_split and not self.cash_allocation_ids and self.cash_fund_id:
            self.cash_allocation_ids = [Command.create({'fund_id': self.cash_fund_id.id, 'amount': self.amount})]
        self.cash_split = not self.cash_split

    def action_toggle_destination_split(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only draft payments can be split.'))
        if not self.cash_destination_split and not self.cash_destination_allocation_ids and self.cash_destination_fund_id:
            self.cash_destination_allocation_ids = [Command.create({
                'fund_id': self.cash_destination_fund_id.id, 'amount': self.amount})]
        self.cash_destination_split = not self.cash_destination_split

    def _validate_cash_side(self, journal, fund, split, allocations):
        self.ensure_one()
        if journal.type != 'cash':
            return
        if not journal.default_account_id:
            raise ValidationError(_('Configure a cash account on the safe first.'))
        if split:
            if not allocations or any(a.amount <= 0 or a.fund_id.journal_id != journal
                                      or not a.fund_id.active for a in allocations):
                raise ValidationError(_('Use positive split amounts and active classifications belonging to this safe.'))
            if not self.currency_id.is_zero(sum(allocations.mapped('amount')) - self.amount):
                raise ValidationError(_('Classification splits must equal the payment total.'))
        elif not fund or fund.journal_id != journal or not fund.active:
            raise ValidationError(_('Select an active classification belonging to this safe.'))

    def _validate_cash_payment(self):
        for payment in self:
            if payment.amount <= 0:
                raise ValidationError(_('The payment amount must be positive.'))
            payment._validate_cash_side(payment.journal_id, payment.cash_fund_id,
                                        payment.cash_split, payment.cash_allocation_ids)
            if payment.cash_is_internal_transfer:
                if payment.payment_type != 'outbound' and not payment.paired_internal_transfer_payment_id:
                    raise ValidationError(_('Start an internal transfer from the source safe or bank.'))
                destination = payment.cash_destination_journal_id
                if not destination or destination == payment.journal_id:
                    raise ValidationError(_('Select a different destination safe or bank.'))
                if destination.type not in ('cash', 'bank') or payment.journal_id.type not in ('cash', 'bank'):
                    raise ValidationError(_('Internal transfers require cash or bank journals.'))
                if destination.company_id != payment.company_id:
                    raise ValidationError(_('Internal transfers must stay within one company.'))
                if (destination.currency_id or destination.company_id.currency_id) != payment.currency_id:
                    raise ValidationError(_('Use journals in the same currency for an internal transfer.'))
                if not payment.company_id.transfer_account_id or not payment.company_id.transfer_account_id.reconcile:
                    raise ValidationError(_('Configure a reconcilable internal transfer account on the company.'))
                payment._validate_cash_side(destination, payment.cash_destination_fund_id,
                    payment.cash_destination_split, payment.cash_destination_allocation_ids)

    def _prepare_move_liquidity_lines(self, default_values):
        vals = super()._prepare_move_liquidity_lines(default_values)
        if self.journal_id.type != 'cash':
            return vals
        self._validate_cash_side(self.journal_id, self.cash_fund_id, self.cash_split, self.cash_allocation_ids)
        for line in vals:
            line['cash_fund_id'] = self.cash_fund_id.id
            line['cash_is_transfer'] = self.cash_is_internal_transfer
            if self.cash_split:
                # Round in company currency, assigning the remainder to the
                # final allocation so the ledger always reconciles exactly.
                remaining = abs(line['balance'])
                commands = [Command.clear()]
                for index, allocation in enumerate(self.cash_allocation_ids):
                    amount = remaining if index == len(self.cash_allocation_ids) - 1 else self.company_currency_id.round(
                        abs(line['balance']) * allocation.amount / self.amount)
                    remaining -= amount
                    if amount:
                        commands.append(Command.create({'fund_id': allocation.fund_id.id, 'amount': amount}))
                line['cash_allocation_ids'] = commands
            else:
                line['cash_allocation_ids'] = [Command.clear()]
        return vals

    def _get_trigger_fields_to_synchronize(self):
        return super()._get_trigger_fields_to_synchronize() + (
            'cash_fund_id', 'cash_split', 'cash_allocation_ids', 'cash_is_internal_transfer')

    def _citadel_authority_fingerprint_values(self):
        parent = getattr(super(), '_citadel_authority_fingerprint_values', None)
        values = parent() if parent else {}
        return {**values, 'cash_is_internal_transfer': self.cash_is_internal_transfer,
                'cash_fund_id': self.cash_fund_id.id, 'cash_split': self.cash_split,
                'cash_allocations': [(a.fund_id.id, a.amount) for a in self.cash_allocation_ids],
                'cash_destination_journal_id': self.cash_destination_journal_id.id,
                'cash_destination_fund_id': self.cash_destination_fund_id.id,
                'cash_destination_split': self.cash_destination_split,
                'cash_destination_allocations': [(a.fund_id.id, a.amount) for a in self.cash_destination_allocation_ids]}

    def _create_cash_transfer_pair(self):
        self.ensure_one()
        destination = self.cash_destination_journal_id
        methods = destination._get_available_payment_method_lines('inbound')
        method = methods.filtered(lambda m: m.code == 'manual')[:1]
        if not method:
            raise UserError(_('Configure a Manual incoming payment method on the destination journal.'))
        pair = self.create({
            'payment_type': 'inbound', 'partner_type': 'customer',
            'cash_is_internal_transfer': True, 'partner_id': False,
            'journal_id': destination.id, 'company_id': self.company_id.id,
            'currency_id': self.currency_id.id, 'amount': self.amount, 'date': self.date,
            'memo': self.memo or _('Internal Transfer'), 'payment_method_line_id': method.id,
            'cash_fund_id': self.cash_destination_fund_id.id,
            'cash_split': self.cash_destination_split,
            'cash_allocation_ids': [Command.create({'fund_id': a.fund_id.id, 'amount': a.amount})
                                    for a in self.cash_destination_allocation_ids] if self.cash_destination_split else [],
            'cash_destination_journal_id': self.journal_id.id,
            'cash_destination_fund_id': self.cash_fund_id.id,
            'cash_destination_split': self.cash_split,
            'cash_destination_allocation_ids': [Command.create({'fund_id': a.fund_id.id, 'amount': a.amount})
                for a in self.cash_allocation_ids] if self.cash_split else [],
        })
        pair.paired_internal_transfer_payment_id = self
        self.paired_internal_transfer_payment_id = pair
        return pair

    def action_post(self):
        actionable = self.filtered(lambda p: p.state == 'draft')
        actionable.filtered(lambda p: p.journal_id.type == 'cash' or p.cash_is_internal_transfer)._validate_cash_payment()
        combined = self
        for payment in actionable.filtered('cash_is_internal_transfer'):
            if not payment.paired_internal_transfer_payment_id:
                combined |= payment._create_cash_transfer_pair()
            else:
                combined |= payment.paired_internal_transfer_payment_id
        # If Authority is installed, both legs must pass its normal approval
        # gate before either leg posts. Never bypass approvals for the pair.
        if hasattr(combined, '_citadel_authority_gate'):
            pending = combined.filtered(lambda p: p.state == 'draft' and not p._citadel_authority_gate())
            if pending:
                pending._citadel_authority_notify_blocked()
                return True
        result = super(AccountPayment, combined).action_post()
        for payment in combined.filtered(lambda p: p.cash_is_internal_transfer and p.payment_type == 'outbound'):
            pair = payment.paired_internal_transfer_payment_id
            if payment.move_id.state == 'posted' and pair.move_id.state == 'posted':
                lines = (payment.move_id | pair.move_id).line_ids.filtered(
                    lambda l: l.account_id == payment.company_id.transfer_account_id and not l.reconciled)
                if lines:
                    lines.reconcile()
                payment.message_post(body=_('Internal transfer paired with %s.', pair.display_name))
        return result

    @api.constrains('state', 'cash_is_internal_transfer', 'paired_internal_transfer_payment_id')
    def _check_posted_cash_transfer_pair(self):
        for payment in self.filtered(lambda p: p.cash_is_internal_transfer and p.state in ('paid', 'reconciled')):
            pair = payment.paired_internal_transfer_payment_id
            if not pair or pair.payment_type == payment.payment_type or pair.company_id != payment.company_id:
                raise ValidationError(_('A confirmed internal transfer requires its matching opposite payment.'))

    def _cash_controlled(self):
        """Payments this module governs: cash-journal payments and transfers.

        Bank, customer and vendor payments keep Odoo's standard behaviour."""
        return self.filtered(lambda p: p.journal_id.type == 'cash' or p.cash_is_internal_transfer)

    def _cash_linked_payments(self):
        transfers = self.filtered('cash_is_internal_transfer')
        return self | transfers.paired_internal_transfer_payment_id

    def _cash_unreconcile_transfers(self):
        transfers = self.filtered('cash_is_internal_transfer')
        transfers.move_id.line_ids.filtered(
            lambda l: l.account_id == l.company_id.transfer_account_id).remove_move_reconcile()

    def action_cancel(self):
        payments = self._cash_linked_payments()
        payments._cash_unreconcile_transfers()
        return super(AccountPayment, payments).action_cancel()

    def action_draft(self):
        payments = self._cash_linked_payments()
        payments._cash_unreconcile_transfers()
        return super(AccountPayment, payments).action_draft()

    def action_reject(self):
        transfers = self.filtered('cash_is_internal_transfer')
        if transfers:
            transfers.action_cancel()
        others = self - transfers
        return super(AccountPayment, others).action_reject() if others else True

    def action_open_cash_pair(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'account.payment', 'view_mode': 'form',
                'res_id': self.paired_internal_transfer_payment_id.id}

    def write(self, vals):
        guarded = {'cash_fund_id', 'cash_split', 'cash_allocation_ids', 'cash_destination_fund_id',
                   'cash_destination_split', 'cash_destination_allocation_ids', 'cash_is_internal_transfer',
                   'cash_destination_journal_id', 'cash_operation', 'amount', 'currency_id', 'journal_id',
                   'date', 'payment_type', 'partner_id', 'destination_account_id', 'company_id'}
        controlled = self._cash_controlled()
        if guarded & vals.keys() and controlled:
            if controlled.filtered(lambda p: p.state not in ('draft', 'canceled')):
                raise UserError(_('Posted payment allocations are locked. Cancel and recreate a transfer to change its allocations.'))
            if controlled.filtered(lambda p: p.cash_is_internal_transfer and p.paired_internal_transfer_payment_id):
                raise UserError(_('This transfer already has a linked payment. Delete the draft transfer and create a corrected one.'))
        return super().write(vals)

    def unlink(self):
        payments = self._cash_linked_payments()
        if any(p.state not in ('draft', 'canceled') for p in payments._cash_controlled()):
            raise UserError(_('Cancel the payment before deleting it.'))
        return super(AccountPayment, payments).unlink()


class CashPaymentAllocation(models.Model):
    _name = 'account.cash.payment.allocation'
    _description = 'Cash Payment Classification Split'
    _check_company_auto = True

    payment_id = fields.Many2one('account.payment', ondelete='cascade', index=True)
    destination_payment_id = fields.Many2one('account.payment', ondelete='cascade', index=True)
    company_id = fields.Many2one('res.company', compute='_compute_company', store=True, precompute=True)
    currency_id = fields.Many2one('res.currency', compute='_compute_parent')
    journal_id = fields.Many2one('account.journal', compute='_compute_parent')
    fund_id = fields.Many2one('account.cash.fund', required=True, check_company=True, ondelete='restrict')
    amount = fields.Monetary(required=True)

    _one_parent = models.Constraint('CHECK ((payment_id IS NULL) != (destination_payment_id IS NULL))',
                                    'A split must belong to exactly one payment side.')

    @api.depends('payment_id.company_id', 'destination_payment_id.company_id')
    def _compute_company(self):
        for allocation in self:
            allocation.company_id = (allocation.payment_id or allocation.destination_payment_id).company_id

    @api.depends('payment_id.currency_id', 'destination_payment_id.currency_id',
                 'payment_id.journal_id', 'destination_payment_id.cash_destination_journal_id')
    def _compute_parent(self):
        for allocation in self:
            payment = allocation.payment_id or allocation.destination_payment_id
            allocation.currency_id = payment.currency_id
            allocation.journal_id = payment.journal_id if allocation.payment_id else payment.cash_destination_journal_id

    def _check_editable(self):
        payments = self.payment_id | self.destination_payment_id
        if any(p.state != 'draft' or p.paired_internal_transfer_payment_id for p in payments):
            raise UserError(_('Only unpaired draft payments can change classifications.'))

    @api.model_create_multi
    def create(self, vals_list):
        parents = self.env['account.payment'].browse([
            v.get('payment_id') or v.get('destination_payment_id') for v in vals_list])
        if any(p.state != 'draft' or p.paired_internal_transfer_payment_id for p in parents):
            raise UserError(_('Only unpaired draft payments can change classifications.'))
        return super().create(vals_list)

    def write(self, vals):
        self._check_editable()
        if {'payment_id', 'destination_payment_id'} & vals.keys():
            raise UserError(_('A split cannot be moved to another payment.'))
        return super().write(vals)

    def unlink(self):
        self._check_editable()
        return super().unlink()
