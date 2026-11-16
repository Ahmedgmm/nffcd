from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestCashFunds(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Cash Fund Test Company', 'currency_id': cls.env.ref('base.USD').id,
            'account_fiscal_country_id': cls.env.ref('base.us').id})
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id]))

        def account(code, name, kind, reconcile=False):
            return cls.env['account.account'].create({
                'name': name, 'code': code, 'account_type': kind, 'reconcile': reconcile,
                'company_ids': [Command.set(cls.company.ids)]})

        cls.receivable = account('1100', 'Receivable', 'asset_receivable', True)
        cls.payable = account('2100', 'Payable', 'liability_payable', True)
        cls.transfer = account('1190', 'Internal Transfer', 'asset_current', True)
        cls.offset = account('3000', 'Opening / Funding', 'equity')
        cls.company.transfer_account_id = cls.transfer
        cls.safe = cls.env['account.journal'].create({'name': 'Test Main Safe', 'code': 'CS1',
            'type': 'cash', 'company_id': cls.company.id})
        cls.safe2 = cls.env['account.journal'].create({'name': 'Test Second Safe', 'code': 'CS2',
            'type': 'cash', 'company_id': cls.company.id})
        cls.misc = cls.env['account.journal'].create({'name': 'Test Adjustments', 'code': 'ADJ',
            'type': 'general', 'company_id': cls.company.id})
        cls.fund = cls.env['account.cash.fund'].create({'name': 'Donations', 'journal_id': cls.safe.id})
        cls.fund2 = cls.env['account.cash.fund'].create({'name': 'Activities', 'journal_id': cls.safe.id})
        cls.destination = cls.env['account.cash.fund'].create({'name': 'Operations', 'journal_id': cls.safe2.id})

    def payment(self, amount, kind='inbound', **values):
        return self.env['account.payment'].create({
            'journal_id': self.safe.id, 'company_id': self.company.id, 'amount': amount,
            'payment_type': kind, 'partner_type': 'customer' if kind == 'inbound' else 'supplier',
            'cash_fund_id': self.fund.id, **values})

    def balance(self, fund):
        fund.invalidate_recordset(['balance', 'receipts', 'spending', 'transfers'])
        return fund.balance

    def test_default_general_and_quick_create(self):
        payment = self.env['account.payment'].create({'journal_id': self.safe.id, 'amount': 20})
        self.assertTrue(payment.cash_fund_id.is_general)
        self.assertEqual(payment.cash_fund_id.name, 'عام')
        result = self.env['account.cash.fund'].with_context(default_journal_id=self.safe.id).name_create('New Fund')
        self.assertEqual(self.env['account.cash.fund'].browse(result[0]).journal_id, self.safe)

    def test_split_receipt_and_payment_reconcile_to_cash(self):
        receipt = self.payment(100, cash_split=True, cash_allocation_ids=[
            Command.create({'fund_id': self.fund.id, 'amount': 60}),
            Command.create({'fund_id': self.fund2.id, 'amount': 40})])
        receipt.action_post()
        spent = self.payment(25, 'outbound')
        spent.action_post()
        self.assertEqual(self.balance(self.fund), 35)
        self.assertEqual(self.balance(self.fund2), 40)
        self.assertEqual(self.fund.receipts, 60)
        self.assertEqual(self.fund.spending, 25)
        cash_balance = sum((receipt.move_id | spent.move_id).line_ids.filtered(
            lambda l: l.account_id == self.safe.default_account_id).mapped('balance'))
        self.assertEqual(self.fund.balance + self.fund2.balance, cash_balance)

    def test_invalid_split_and_wrong_safe_are_rejected(self):
        payment = self.payment(100, cash_split=True, cash_allocation_ids=[
            Command.create({'fund_id': self.fund.id, 'amount': 99})])
        with self.assertRaises(ValidationError), self.cr.savepoint():
            payment.action_post()
        payment = self.payment(100, cash_fund_id=self.destination.id)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            payment.action_post()

    def test_internal_transfer_pair_and_cancellation(self):
        self.payment(200).action_post()
        transfer = self.payment(75, 'outbound', cash_is_internal_transfer=True,
            cash_destination_journal_id=self.safe2.id, cash_destination_fund_id=self.destination.id)
        transfer.action_post()
        pair = transfer.paired_internal_transfer_payment_id
        self.assertEqual(pair.paired_internal_transfer_payment_id, transfer)
        self.assertEqual(pair.move_id.state, 'posted')
        self.assertEqual(self.balance(self.fund), 125)
        self.assertEqual(self.balance(self.destination), 75)
        self.assertEqual(self.fund.spending, 0)
        self.assertEqual(self.destination.receipts, 0)
        self.assertTrue(all((transfer.move_id | pair.move_id).line_ids.filtered(
            lambda l: l.account_id == self.transfer).mapped('reconciled')))
        transfer.action_cancel()
        self.assertEqual(pair.state, 'canceled')
        self.assertEqual(self.balance(self.fund), 200)
        self.assertEqual(self.balance(self.destination), 0)

    def test_transfer_splits_both_sides_and_repost(self):
        self.payment(100).action_post()
        transfer = self.payment(30, 'outbound', cash_is_internal_transfer=True,
            cash_split=True, cash_allocation_ids=[Command.create({'fund_id': self.fund.id, 'amount': 30})],
            cash_destination_journal_id=self.safe2.id, cash_destination_split=True,
            cash_destination_allocation_ids=[
                Command.create({'fund_id': self.destination.id, 'amount': 20}),
                Command.create({'fund_id': self.safe2.cash_fund_ids.filtered('is_general').id, 'amount': 10})])
        transfer.action_post()
        self.assertEqual(self.balance(self.destination), 20)
        transfer.action_draft()
        self.assertEqual(self.balance(self.destination), 0)
        transfer.action_post()
        self.assertEqual(self.balance(self.destination), 20)
        self.assertEqual(self.env['account.payment'].search_count([
            ('paired_internal_transfer_payment_id', '=', transfer.id)]), 1)

    def test_balance_guard_and_posted_immutability(self):
        self.payment(50).action_post()
        payment = self.payment(51, 'outbound')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            payment.action_post()
        self.assertEqual(self.balance(self.fund), 50)
        paid = self.payment(10, 'outbound')
        paid.action_post()
        with self.assertRaises(UserError), self.cr.savepoint():
            paid.cash_fund_id = self.fund2
        with self.assertRaises(UserError), self.cr.savepoint():
            paid._seek_for_lines()[0].cash_fund_id = self.fund2

    def test_opening_adjustment_reversal_and_statement(self):
        opening = self.env['account.move'].create({'journal_id': self.misc.id,
            'date': '2026-01-01', 'line_ids': [
                Command.create({'account_id': self.safe.default_account_id.id, 'debit': 120,
                                'cash_fund_id': self.fund.id}),
                Command.create({'account_id': self.offset.id, 'credit': 120})]})
        opening.action_post()
        self.assertEqual(self.balance(self.fund), 120)
        statement = self.env['account.cash.statement'].create({'fund_id': self.fund.id,
            'date_from': '2026-02-01', 'date_to': '2026-02-28'})
        self.assertEqual(statement._statement_values()['opening'], 120)
        opening._reverse_moves([{'date': '2026-02-01'}], cancel=True)
        self.assertEqual(self.balance(self.fund), 0)
        self.assertEqual(statement._statement_values()['closing'], 0)
        html, _ = self.env['ir.actions.report']._render_qweb_html(
            'nffcd_accounting_enhancement.action_cash_statement_pdf', statement.ids)
        self.assertIn(b'Cash Classification Statement', html)

    def test_reclassification_preserves_safe_balance(self):
        self.payment(100).action_post()
        wizard = self.env['account.cash.reclassification'].create({
            'company_id': self.company.id, 'journal_id': self.safe.id,
            'source_fund_id': self.fund.id, 'destination_fund_id': self.fund2.id,
            'amount': 30, 'reason': 'Approved funding reallocation'})
        move = self.env['account.move'].browse(wizard.action_create()['res_id'])
        self.assertEqual(move.state, 'draft')
        move.action_post()
        self.assertEqual(self.balance(self.fund), 70)
        self.assertEqual(self.balance(self.fund2), 30)
        self.assertEqual(self.fund.spending, 0)
        self.assertEqual(self.fund2.receipts, 0)

    def test_transfer_type_from_payment_form(self):
        self.payment(10, cash_fund_id=self.safe.cash_fund_ids.filtered('is_general').id).action_post()
        with Form(self.env['account.payment'].with_context(default_journal_id=self.safe.id)) as form:
            form.cash_operation = 'transfer'
            form.amount = 10
            form.cash_destination_journal_id = self.safe2
        payment = form.record
        self.assertEqual(payment.payment_type, 'outbound')
        self.assertTrue(payment.cash_is_internal_transfer)
        payment.action_post()
        self.assertEqual(payment.paired_internal_transfer_payment_id.payment_type, 'inbound')

    def test_split_reversal_restores_each_fund(self):
        payment = self.payment(100, cash_split=True, cash_allocation_ids=[
            Command.create({'fund_id': self.fund.id, 'amount': 60}),
            Command.create({'fund_id': self.fund2.id, 'amount': 40})])
        payment.action_post()
        payment.move_id._reverse_moves([{'date': fields.Date.today()}], cancel=True)
        self.assertEqual(self.balance(self.fund), 0)
        self.assertEqual(self.balance(self.fund2), 0)

    def test_bank_to_cash_transfer(self):
        bank = self.env['account.journal'].create({'name': 'Test Bank', 'type': 'bank',
            'code': 'BK1', 'company_id': self.company.id})
        bank.outbound_payment_method_line_ids.payment_account_id = bank.default_account_id
        payment = self.payment(45, 'outbound', journal_id=bank.id, cash_fund_id=False,
            cash_is_internal_transfer=True, cash_destination_journal_id=self.safe.id,
            cash_destination_fund_id=self.fund.id)
        payment.action_post()
        self.assertEqual(self.balance(self.fund), 45)
        self.assertEqual(self.fund.receipts, 0)

    def test_company_security(self):
        other = self.env['res.company'].create({'name': 'Other Cash Company'})
        user = new_test_user(self.env, login='cash.test.reader', groups='account.group_account_manager',
                             company_id=other.id, company_ids=[Command.set(other.ids)])
        funds = self.env['account.cash.fund'].with_user(user).with_context(allowed_company_ids=other.ids)
        self.assertFalse(funds.search([('id', '=', self.fund.id)]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            funds.browse(self.fund.id).read(['name'])
        self.payment(20).action_post()
        report = self.env['account.cash.fund.report'].with_user(user).with_context(allowed_company_ids=other.ids)
        self.assertFalse(report.search([('fund_id', '=', self.fund.id)]))

    def test_register_bill_payment_with_classification_split(self):
        partner = self.env['res.partner'].create({'name': 'Cash Test Supplier'})
        partner.with_company(self.company).property_account_payable_id = self.payable
        bill = self.env['account.move'].create({'move_type': 'in_invoice', 'partner_id': partner.id,
            'journal_id': self.env['account.journal'].create({'name': 'Test Purchases', 'code': 'PUR',
                'type': 'purchase', 'company_id': self.company.id}).id,
            'invoice_date': fields.Date.today(), 'invoice_line_ids': [Command.create({
                'name': 'Test service', 'account_id': self.offset.id, 'price_unit': 100})]})
        bill.action_post()
        self.payment(60).action_post()
        self.payment(40, cash_fund_id=self.fund2.id).action_post()
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids).create({
                'journal_id': self.safe.id, 'cash_split': True,
                'cash_allocation_ids': [Command.create({'fund_id': self.fund.id, 'amount': 60}),
                                        Command.create({'fund_id': self.fund2.id, 'amount': 40})]})
        payments = wizard._create_payments()
        self.assertEqual(self.balance(self.fund), 0)
        self.assertEqual(self.balance(self.fund2), 0)
        self.assertEqual(self.fund.spending, 60)
        self.assertTrue(payments.cash_split)

    def test_inbound_unpaired_transfer_cannot_create_money(self):
        payment = self.payment(100, 'inbound', cash_is_internal_transfer=True,
            cash_destination_journal_id=self.safe2.id, cash_destination_fund_id=self.destination.id)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            payment.action_post()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            payment.write({'state': 'paid'})

    def test_negative_balance_always_blocked(self):
        self.assertNotIn('allow_negative', self.env['account.cash.fund']._fields)
        payment = self.payment(1, 'outbound')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            payment.action_post()
        self.assertEqual(self.balance(self.fund), 0)

    def test_bank_payments_are_not_governed(self):
        bank = self.env['account.journal'].create({'name': 'Test Bank 2', 'type': 'bank',
            'code': 'BK2', 'company_id': self.company.id})
        payment = self.env['account.payment'].create({'journal_id': bank.id, 'amount': 30,
            'company_id': self.company.id, 'payment_type': 'inbound', 'partner_type': 'customer'})
        self.assertFalse(payment._cash_controlled())
        self.assertEqual(payment._cash_linked_payments(), payment)
        self.assertFalse(payment.cash_fund_id)

    def test_new_safe_relinks_existing_cash_items(self):
        account = self.env['account.account'].create({'name': 'Petty Cash', 'code': '1050',
            'account_type': 'asset_cash', 'company_ids': [Command.set(self.company.ids)]})
        entry = self.env['account.move'].create({'journal_id': self.misc.id, 'line_ids': [
            Command.create({'account_id': account.id, 'debit': 40}),
            Command.create({'account_id': self.offset.id, 'credit': 40})]})
        entry.action_post()
        cash_line = entry.line_ids.filtered(lambda l: l.account_id == account)
        self.assertFalse(cash_line.cash_journal_id)
        petty = self.env['account.journal'].create({'name': 'Petty Safe', 'code': 'PTY', 'type': 'cash',
            'company_id': self.company.id, 'default_account_id': account.id})
        general = petty.cash_fund_ids.filtered('is_general')
        self.assertEqual(cash_line.cash_journal_id, petty)
        self.assertEqual(cash_line.cash_fund_id, general)
        self.assertEqual(self.balance(general), 40)

    def test_safe_group_totals(self):
        self.payment(70).action_post()
        self.payment(30, cash_fund_id=self.fund2.id).action_post()
        self.payment(20, 'outbound').action_post()
        rows = self.env['account.cash.fund']._read_group(
            [('journal_id', '=', self.safe.id)], ['journal_id'],
            ['balance:sum', 'receipts:sum', 'spending:sum'])
        self.assertEqual(rows, [(self.safe, 80, 100, 20)])
        self.assertTrue(self.env['account.cash.fund'].fields_get(['balance'])['balance'].get('aggregator'))
