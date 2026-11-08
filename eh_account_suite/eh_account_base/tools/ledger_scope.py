"""Native Odoo 20 ledger selection shared by report entry points."""

from odoo.exceptions import AccessError, UserError


def _ids(env, values):
    if not isinstance(values, (list, tuple)):
        raise UserError(env._("Ledger IDs must be a list of positive integers."))
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
           for value in values):
        raise UserError(env._("Ledger IDs must be a list of positive integers."))
    return sorted(set(values))


def resolve_ledger_scope(env, options):
    """Resolve public options through caller-visible journals, never sudo.

    Ledger groups are global in Odoo 20. A group is selectable only when it
    has a readable journal in the requested allowed-company scope. Private
    resolved IDs from an RPC or old execution are always discarded/rebuilt.
    """
    scope = options.get('ledger_scope', 'statutory')
    if scope not in ('statutory', 'all', 'selected'):
        raise UserError(env._("Choose statutory, all, or selected ledgers."))
    group_ids = _ids(env, options.get('ledger_group_ids') or [])
    companies = _ids(env, options.get('company_ids') or env.companies.ids)
    if not companies or set(companies) - set(env.companies.ids):
        raise AccessError(env._("Ledger companies must be in your allowed company scope."))
    domain = [('company_id', 'in', companies)]
    Journal = env['account.journal'].with_context(active_test=False)
    if scope == 'statutory':
        domain.append(('journal_group_id', '=', False))
        group_ids = []
        label = env._("Statutory (Local GAAP)")
    elif scope == 'selected':
        if not group_ids:
            raise UserError(env._("Select at least one adjustment ledger."))
        groups = env['account.journal.group'].search([('id', 'in', group_ids)])
        visible = Journal.search(domain + [('journal_group_id', 'in', group_ids)])
        if set(groups.ids) != set(group_ids) or set(visible.journal_group_id.ids) != set(group_ids):
            raise AccessError(env._("Selected ledgers must have accessible journals in the report companies."))
        domain.append(('journal_group_id', 'in', group_ids))
        label = env._("Selected adjustment ledgers: %s", ', '.join(groups.sorted('id').mapped('name')))
    else:
        group_ids = []
        label = env._("All ledgers (statutory and adjustments)")
    return {
        'ledger_scope': scope,
        'ledger_group_ids': group_ids,
        '_eh_ledger_journal_ids': sorted(Journal.search(domain).ids),
        '_eh_ledger_label': label,
    }
