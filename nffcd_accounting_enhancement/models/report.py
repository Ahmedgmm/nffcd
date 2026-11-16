from odoo import fields, models, tools


class CashFundReport(models.Model):
    _name = 'account.cash.fund.report'
    _description = 'Posted Cash Classification Movement'
    _auto = False
    _order = 'date, move_id, id'

    date = fields.Date(readonly=True)
    fund_id = fields.Many2one('account.cash.fund', string='Classification', readonly=True)
    journal_id = fields.Many2one('account.journal', string='Safe', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    move_id = fields.Many2one('account.move', string='Journal Entry', readonly=True)
    move_line_id = fields.Many2one('account.move.line', readonly=True)
    payment_id = fields.Many2one('account.payment', readonly=True)
    partner_id = fields.Many2one('res.partner', readonly=True)
    reference = fields.Char(readonly=True)
    is_transfer = fields.Boolean(readonly=True)
    balance = fields.Monetary(string='Net Movement', readonly=True)
    receipts = fields.Monetary(readonly=True)
    spending = fields.Monetary(readonly=True)
    transfers = fields.Monetary(string='Net Transfers', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute('''
            CREATE VIEW account_cash_fund_report AS
            SELECT x.*, CASE WHEN NOT is_transfer AND balance > 0 THEN balance ELSE 0 END AS receipts,
                   CASE WHEN NOT is_transfer AND balance < 0 THEN -balance ELSE 0 END AS spending,
                   CASE WHEN is_transfer THEN balance ELSE 0 END AS transfers
            FROM (
                SELECT CASE WHEN a.id IS NULL THEN l.id::bigint * 2 ELSE a.id::bigint * 2 + 1 END AS id,
                       l.date, COALESCE(a.fund_id, l.cash_fund_id, g.id) AS fund_id,
                       j.id AS journal_id, l.company_id, c.currency_id,
                       l.move_id, l.id AS move_line_id, m.origin_payment_id AS payment_id,
                       l.partner_id, COALESCE(m.ref, l.name) AS reference,
                       COALESCE(l.cash_is_transfer, FALSE) AS is_transfer,
                       CASE WHEN a.id IS NULL THEN l.balance
                            WHEN l.balance < 0 THEN -a.amount ELSE a.amount END AS balance
                FROM account_move_line l
                JOIN account_move m ON m.id = l.move_id AND m.state = 'posted'
                JOIN res_company c ON c.id = l.company_id
                JOIN account_journal j ON j.id = l.cash_journal_id
                LEFT JOIN account_cash_fund g ON g.journal_id = j.id AND g.is_general
                LEFT JOIN account_cash_move_allocation a ON a.move_line_id = l.id
            ) x
        ''')

    def action_open_entry(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move',
                'view_mode': 'form', 'res_id': self.move_id.id}
