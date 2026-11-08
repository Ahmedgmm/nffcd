# -*- encoding: utf-8 -*-
"""Replace legacy company-closure restrictions despite their noupdate flag.

Odoo 20 folds record rules into ``ir.access``: every former global rule is
a group-less restriction row that keeps its XML ID and its noupdate flag,
so a stale domain carried over from an older database is never refreshed
by the module data. Rewrite it here.
"""

from odoo import SUPERUSER_ID, api


_COMPANY_SCOPE_DOMAIN = "[('eh_company_scope_allowed', '=', True)]"
_RULE_XMLIDS = (
    'eh_account_consolidation.eh_consol_entity_company_rule',
    'eh_account_consolidation.eh_consol_member_company_rule',
    'eh_account_consolidation.eh_consol_run_company_rule',
    'eh_account_consolidation.eh_consol_run_line_company_rule',
    'eh_account_consolidation.eh_consol_elimination_company_rule',
    'eh_account_consolidation.eh_consol_elimination_line_company_rule',
    'eh_account_consolidation.eh_consol_unrealised_profit_company_rule',
)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    restrictions = env['ir.access']
    missing = []
    for xmlid in _RULE_XMLIDS:
        restriction = env.ref(xmlid, raise_if_not_found=False)
        if not restriction or restriction._name != 'ir.access':
            missing.append(xmlid)
        else:
            restrictions |= restriction
    if missing:
        raise RuntimeError(
            "Missing consolidation company-closure restriction(s): %s"
            % ', '.join(missing)
        )
    if len(restrictions) != len(_RULE_XMLIDS):
        raise RuntimeError(
            "Consolidation company-closure restriction XML IDs are not "
            "unique."
        )
    stale = restrictions.filtered(
        lambda restriction: restriction.domain != _COMPANY_SCOPE_DOMAIN,
    )
    if stale:
        stale.write({'domain': _COMPANY_SCOPE_DOMAIN})
