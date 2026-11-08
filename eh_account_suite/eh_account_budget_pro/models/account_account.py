# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Budget lines stay on accounts without sub-accounts.

In Odoo 20 any account can be the parent of other accounts, and a parent
account's own journal items exclude those of its sub-accounts. Every budget
consumer (budget vs actual, line actuals, commitments, the budget columns of
the dynamic reports) matches journal items on the budget line's own account,
so a budget line on a parent account would show the sub-accounts' spending
as zero: a false underspend. Budget lines are therefore kept on accounts
that have no sub-accounts, as every account was in Odoo 19.
"""

from odoo import _, api, models
from odoo.exceptions import ValidationError


class AccountAccount(models.Model):
    _inherit = 'account.account'

    def _eh_assert_budgetable_account(self):
        """Refuse a budget line on an account that has sub-accounts."""
        Account = self.env['account.account'].sudo().with_context(
            active_test=False,
        )
        for account in self:
            children = Account.search_count([('parent_id', '=', account.id)])
            if children:
                raise ValidationError(_(
                    "Account %(account)s has %(count)s sub-account(s). A "
                    "budget line follows the journal items of its own account "
                    "only, so it would not see the sub-accounts' postings. "
                    "Budget each sub-account instead.",
                    account=account.sudo().display_name,
                    count=children,
                ))

    @api.constrains('parent_id')
    def _check_eh_budgeted_account_stays_without_sub_accounts(self):
        parents = self.sudo().parent_id
        if not parents:
            return
        line = self.env['eh.budget.line'].sudo().search([
            ('account_id', 'in', parents.ids),
            ('budget_id.state', '!=', 'closed'),
        ], limit=1)
        if line:
            raise ValidationError(_(
                "Account %(account)s carries lines of budget %(budget)s. A "
                "budget line follows the journal items of its own account "
                "only, so this account cannot receive sub-accounts while an "
                "open budget uses it. Budget the posting accounts instead, "
                "or close that budget first.",
                account=line.account_id.display_name,
                budget=line.budget_id.display_name,
            ))
