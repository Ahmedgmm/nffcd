##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""The two menu layouts the suite supports, for tests of either database.

On a Community database the finance root account.menu_finance is the
Accounting app. With the Enterprise accountant module installed the
Accounting app is accountant.menu_accounting, and accountant's data moves
the core finance sections into it. Tests that need the Enterprise layout on
a Community database build it the way that data file does, inside the test
transaction.
"""

FINANCE_ROOT = 'account.menu_finance'
ENTERPRISE_ROOT = 'accountant.menu_accounting'

# Sections accountant/data/account_accountant_data.xml moves into its app.
ENTERPRISE_CORE_SECTIONS = (
    'account.menu_board_journal_1',
    'account.menu_finance_receivables',
    'account.menu_finance_payables',
    'account.menu_finance_entries',
    'account.account_audit_menu',
    'account.menu_finance_reports',
    'account.menu_finance_configuration',
)


def accounting_app(env):
    """The one app a user opens for accounting on this database."""
    return (
        env.ref(ENTERPRISE_ROOT, raise_if_not_found=False)
        or env.ref(FINANCE_ROOT)
    )


def is_enterprise_layout(env):
    return bool(env.ref(ENTERPRISE_ROOT, raise_if_not_found=False))


def build_enterprise_app(env):
    """Return the Enterprise Accounting app, creating it on Community.

    Mirrors what installing accountant does to the menus: a new root named
    Accounting under the external ID accountant.menu_accounting, holding
    the core finance sections. The suite's own sections are left where they
    are, exactly as accountant leaves them.
    """
    host = env.ref(ENTERPRISE_ROOT, raise_if_not_found=False)
    if host:
        return host
    finance = env.ref(FINANCE_ROOT)
    host = env['ir.ui.menu'].create({
        'name': 'Accounting',
        'sequence': 60,
        'group_ids': [(6, 0, finance.group_ids.ids)],
    })
    env['ir.model.data'].create({
        'module': 'accountant',
        'name': 'menu_accounting',
        'model': 'ir.ui.menu',
        'res_id': host.id,
    })
    for xmlid in ENTERPRISE_CORE_SECTIONS:
        section = env.ref(xmlid, raise_if_not_found=False)
        if section:
            section.parent_id = host
    return host


def own_sections_under(env, parent):
    """Direct children of ``parent`` owned by an ERP Heritage module."""
    children = env['ir.ui.menu'].with_context(active_test=False).search([
        ('parent_id', '=', parent.id),
    ])
    modules = {
        data.res_id: data.module
        for data in env['ir.model.data'].search([
            ('model', '=', 'ir.ui.menu'),
            ('res_id', 'in', children.ids),
        ])
    }
    return children.filtered(
        lambda menu: modules.get(menu.id, '').startswith('eh_'),
    )
