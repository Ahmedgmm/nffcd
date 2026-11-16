from . import models
from . import wizard


def post_init_hook(env):
    env['account.journal']._check_cash_accounts_not_shared()
    env['account.journal'].search([('type', '=', 'cash')])._ensure_general_cash_fund()
