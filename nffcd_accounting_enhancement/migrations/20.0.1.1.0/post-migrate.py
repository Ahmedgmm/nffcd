"""Remove the negative-balance switch and re-link every cash journal item.

The movement report now reads the stored ``cash_journal_id`` instead of
re-joining on the safe's cash account, so the stored value must be exact.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['account.journal']._check_cash_accounts_not_shared()
    cr.execute("""
        UPDATE account_move_line l
           SET cash_journal_id = j.id
          FROM account_journal j
         WHERE j.type = 'cash' AND j.default_account_id = l.account_id
           AND j.company_id = l.company_id
           AND l.cash_journal_id IS DISTINCT FROM j.id
    """)
    cr.execute("""
        UPDATE account_move_line l
           SET cash_journal_id = NULL, cash_fund_id = NULL
         WHERE l.cash_journal_id IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM account_journal j
                            WHERE j.id = l.cash_journal_id AND j.type = 'cash'
                              AND j.default_account_id = l.account_id
                              AND j.company_id = l.company_id)
    """)
    cr.execute("""
        UPDATE account_move_line l
           SET cash_fund_id = g.id
          FROM account_cash_fund g
         WHERE g.journal_id = l.cash_journal_id AND g.is_general
           AND (l.cash_fund_id IS NULL OR NOT EXISTS (
                SELECT 1 FROM account_cash_fund f
                 WHERE f.id = l.cash_fund_id AND f.journal_id = l.cash_journal_id))
    """)
    env.invalidate_all()
