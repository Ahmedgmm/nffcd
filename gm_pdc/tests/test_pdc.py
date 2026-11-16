from odoo import Command, fields
from odoo.exceptions import UserError, AccessError
from odoo.tests import tagged, new_test_user
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestPDC(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.journal = cls.company_data['default_journal_bank']
        cls.accounts = cls.env['account.account']
        for index in range(4):
            cls.accounts |= cls.env['account.account'].create({
                'name': 'PDC Stage %s' % index, 'code': 'PDC%s' % index,
                'account_type': 'asset_current', 'reconcile': True,
            })
        for stage, account in zip(('registered', 'deposited', 'bounced', 'done'), cls.accounts):
            cls.journal.write({
                'pdc_%s_active' % stage: True,
                'pdc_%s_account_id' % stage: account.id,
                'pdc_payable_%s_account_id' % stage: account.id,
            })

    def make_pdc(self, direction='inbound', invoice=False):
        return self.env['account.pdc'].create({
            'partner_id': self.partner_a.id, 'amount': 100,
            'journal_id': self.journal.id, 'payment_type': direction,
            'invoice_ids': [Command.set(invoice.ids)] if invoice else [],
        })

    def test_customer_and_vendor_lifecycle(self):
        for direction, move_type, account in (
            ('inbound', 'out_invoice', self.company_data['default_account_revenue']),
            ('outbound', 'in_invoice', self.company_data['default_account_expense']),
        ):
            invoice = self.env['account.move'].create({
                'move_type': move_type, 'partner_id': self.partner_a.id,
                'invoice_date': fields.Date.today(),
                'invoice_line_ids': [Command.create({'name': 'PDC test', 'account_id': account.id, 'quantity': 1, 'price_unit': 100, 'tax_ids': [Command.clear()]})],
            })
            invoice.action_post()
            pdc = self.make_pdc(direction, invoice)
            self.assertNotEqual(pdc.name, "New")
            pdc.action_register()
            self.assertEqual(pdc.payment_id.move_id.state, 'posted')
            self.assertEqual(invoice.amount_residual, 0)
            self.assertEqual(invoice.payment_state, 'in_payment')
            with self.assertRaises(UserError):
                pdc.action_register()
            pdc.action_deposit()
            with self.assertRaises(UserError):
                pdc.action_deposit()
            pdc.action_done()
            self.assertEqual(pdc.state, 'done')
            self.assertEqual(invoice.payment_state, 'paid')
            self.assertEqual(len(pdc.move_ids), 3)
            for move in pdc.move_ids:
                self.assertAlmostEqual(sum(move.line_ids.mapped('balance')), 0)
            self.assertTrue(all(pdc.move_ids.line_ids.filtered(lambda l: l.account_id in self.accounts[:2]).mapped('reconciled')))
            with self.assertRaises(UserError):
                pdc.action_cancel()

    def test_bounce_cancel_reset(self):
        pdc = self.make_pdc()
        pdc.action_register()
        payment = pdc.payment_id
        pdc.action_deposit()
        pdc.action_bounce()
        self.assertEqual(pdc.holding_account_id, self.accounts[2])
        pdc.action_cancel()
        self.assertEqual(payment.state, 'canceled')
        self.assertTrue(all(m.state == 'cancel' for m in pdc.move_ids))
        pdc.action_draft()
        self.assertFalse(pdc.payment_id)
        pdc.action_register()
        self.assertNotEqual(pdc.payment_id, payment)
        pdc.action_deposit()
        pdc.action_done()
        self.assertEqual(pdc.state, "done")

    def test_validation_and_tracking_only(self):
        with self.assertRaises(UserError), self.cr.savepoint():
            self.make_pdc().write({'amount': 0})
        pdc = self.make_pdc()
        with self.assertRaises(UserError):
            pdc.action_done()
        self.journal.pdc_registered_account_id = False
        with self.assertRaises(UserError):
            pdc.action_register()
        self.journal.write({f'pdc_{stage}_active': False for stage in ('registered', 'deposited', 'bounced', 'done')})
        pdc.action_register()
        pdc.action_deposit()
        pdc.action_done()
        self.assertFalse(pdc.move_ids)

    def test_access_and_company_isolation(self):
        user = new_test_user(self.env, login='pdc_internal', groups='base.group_user')
        with self.assertRaises(AccessError):
            self.make_pdc().with_user(user).read(['name'])
        other_company = self.env['res.company'].create({'name': 'PDC Other'})
        other = self.make_pdc()
        # Record rules must hide records belonging to a disallowed company.
        with self.assertRaises(UserError), self.cr.savepoint():
            other.company_id = other_company
        other_journal = self.env['account.journal'].create({'name': 'Other bank', 'code': 'OPDC', 'type': 'bank', 'company_id': other_company.id})
        other.write({'company_id': other_company.id, 'journal_id': other_journal.id})
        accountant = new_test_user(self.env, login='pdc_accountant', groups='account.group_account_user', company_id=self.env.company.id)
        self.assertFalse(self.env['account.pdc'].with_user(accountant).search([('id', '=', other.id)]))

    def test_foreign_currency(self):
        currency = self.env['res.currency'].create({'name': 'PDC', 'symbol': 'P', 'rounding': 0.01})
        self.env['res.currency.rate'].create({'currency_id': currency.id, 'company_id': self.env.company.id, 'name': fields.Date.today(), 'rate': 2})
        pdc = self.make_pdc()
        pdc.currency_id = currency
        pdc.action_register()
        pdc.action_deposit()
        pdc.action_done()
        for move in pdc.move_ids:
            self.assertAlmostEqual(sum(move.line_ids.mapped('balance')), 0)
            self.assertTrue(all(line.currency_id == currency for line in move.line_ids))
            self.assertAlmostEqual(sum(move.line_ids.mapped('amount_currency')), 0)
        deposit = pdc.move_ids.sorted('id')[1]
        self.assertAlmostEqual(sum(deposit.line_ids.mapped('debit')), 50)

    def test_partial_payment_and_cancel_reopens_invoice(self):
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.partner_a.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [Command.create({'name': 'Partial PDC', 'account_id': self.company_data['default_account_revenue'].id, 'quantity': 1, 'price_unit': 200, 'tax_ids': [Command.clear()]})],
        })
        invoice.action_post()
        pdc = self.make_pdc(invoice=invoice)
        pdc.action_register()
        self.assertEqual(invoice.amount_residual, 100)
        self.assertEqual(invoice.payment_state, 'partial')
        with self.assertRaises(UserError):
            pdc.amount = 150
        with self.assertRaises(UserError):
            pdc.unlink()
        pdc.action_cancel()
        self.assertEqual(invoice.amount_residual, 200)
        self.assertEqual(invoice.payment_state, 'not_paid')

    def test_missing_stage_account(self):
        pdc = self.make_pdc()
        pdc.action_register()
        self.journal.pdc_deposited_account_id = False
        with self.assertRaises(UserError):
            pdc.action_deposit()
        self.assertEqual(pdc.state, 'registered')
        self.assertEqual(len(pdc.move_ids), 1)

    def test_views_and_invoice_action(self):
        for xmlid, model, view_type in (
            ('gm_pdc.view_account_pdc_form', 'account.pdc', 'form'),
            ('gm_pdc.view_account_pdc_tree', 'account.pdc', 'list'),
            ('account.view_move_form', 'account.move', 'form'),
            ('account.view_account_journal_form', 'account.journal', 'form'),
        ):
            self.assertTrue(self.env[model].get_view(self.env.ref(xmlid).id, view_type)['arch'])
        move = self.env['account.move'].create({'move_type': 'entry', 'journal_id': self.journal.id})
        with self.assertRaises(UserError):
            move.action_register_pdc()
