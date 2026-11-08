"""Versioned migration to native customer/company credit-limit authority."""

from collections import defaultdict

from odoo.exceptions import AccessError
from odoo.tools import SQL


def unify_native_credit_limits(env):
    """Keep originals, adopt unambiguous terms and create explicit conflicts.

    Native values that were explicitly configured are never overwritten when
    they differ. An absent native override is filled from the former EH terms.
    Company-policy amounts become the native company default; assigned custom
    policy amounts become explicit customer terms before policies stop owning
    numeric amounts. Every conflict blocks the affected posting scope until
    a manager chooses a value using the retained review record.
    """
    if not env.su:
        raise AccessError('Credit-limit migration requires superuser mode.')
    env.flush_all()
    Review = env['eh.credit.limit.review']
    Partner = env['res.partner'].with_context(active_test=False)
    Policy = env['eh.credit.policy'].with_context(active_test=False)
    companies = env['res.company'].with_context(active_test=False).search([])
    policies = Policy.search([])
    active_defaults = {
        policy.company_id.id: policy for policy in policies
        if policy.active and policy.is_company_default
    }
    native_defaults = {company.id: company.account_credit_limit for company in companies}
    explicit_defaults = env['ir.default'].search([
        ('field_id.model', '=', 'res.partner'), ('field_id.name', '=', 'credit_limit'),
        ('user_id', '=', False), ('condition', '=', False),
    ])
    default_company_ids = set(explicit_defaults.mapped('company_id').ids)
    has_global_default = any(not default.company_id for default in explicit_defaults)
    for company in companies:
        policy = active_defaults.get(company.id)
        if not policy:
            continue
        previous = policy.eh_credit_policy_limit_legacy
        native = native_defaults[company.id]
        if company.currency_id.compare_amounts(native, previous) == 0:
            continue
        if company.id in default_company_ids or has_global_default:
            Review._create_upgrade_review(
                company, Partner, native, previous,
                'Company default policy %s' % policy.id,
            )
        else:
            company.account_credit_limit = previous

    # Read historical JSON as a whole: an upgrade must preserve every company,
    # including inactive companies not enabled in the current user context.
    rows = env.execute_query(SQL("""
        SELECT id, commercial_partner_id, credit_limit,
               eh_credit_limit_legacy, eh_credit_policy_id
          FROM res_partner
         WHERE credit_limit IS NOT NULL OR eh_credit_limit_legacy IS NOT NULL
            OR eh_credit_policy_id IS NOT NULL
         ORDER BY id
    """))
    roots = {row[0]: row[1] or row[0] for row in rows}
    native_by_partner = {row[0]: row[2] or {} for row in rows}
    terms = defaultdict(list)
    policy_by_id = {policy.id: policy for policy in policies}
    company_by_id = {company.id: company for company in companies}
    for partner_id, root_id, native, previous_limits, assigned in rows:
        root_id = root_id or partner_id
        native = native or {}
        previous_limits = previous_limits or {}
        assigned = assigned or {}
        # Native child values are commercial copies, not separate authorities.
        keys = set(previous_limits) | set(assigned)
        if root_id == partner_id:
            keys |= set(native)
        for key in sorted(keys):
            company = company_by_id.get(int(key))
            if not company:
                continue
            policy = policy_by_id.get(assigned.get(key))
            if not policy or not policy.active:
                policy = active_defaults.get(company.id)
            previous = float(previous_limits.get(key) or 0.0)
            explicit_eh = previous > 0.0
            if not explicit_eh:
                if not policy:
                    continue
                previous = policy.eh_credit_policy_limit_legacy
            # A child with no historical independent terms needs no action.
            if root_id != partner_id and not explicit_eh and key not in assigned:
                continue
            terms[(root_id, company.id)].append((previous, partner_id, explicit_eh or key in assigned))
    for (partner_id, company_id), candidates in terms.items():
        company = company_by_id[company_id]
        partner = Partner.browse(partner_id).with_company(company)
        explicit_native = str(company_id) in native_by_partner.get(partner_id, {})
        native = partner.credit_limit
        for previous, source_partner, explicit_eh in candidates:
            if company.currency_id.compare_amounts(native, previous) == 0:
                continue
            source = 'Previous customer terms %s' % source_partner
            if explicit_native or source_partner != partner_id or len({candidate[0] for candidate in candidates}) > 1:
                Review._create_upgrade_review(company, partner, native, previous, source)
            elif explicit_eh:
                partner.credit_limit = previous
                native = previous
            # No explicit customer terms means the single company-default
            # migration (and its conflict, if any) already governs the customer.
    return True
