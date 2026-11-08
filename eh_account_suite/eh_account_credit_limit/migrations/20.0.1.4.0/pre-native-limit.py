"""Retain original EH values before replacing fields with native aliases."""


def migrate(cr, version):
    if not version:
        return
    cr.execute("ALTER TABLE res_partner ADD COLUMN IF NOT EXISTS eh_credit_limit_legacy jsonb")
    cr.execute("""
        UPDATE res_partner
           SET eh_credit_limit_legacy = COALESCE(eh_credit_limit_legacy, eh_credit_limit),
               eh_credit_limit = NULL
         WHERE eh_credit_limit IS NOT NULL
    """)
    # Clearing the obsolete column also prevents the older commercial-root
    # post-migration from applying values before conflicts have been reviewed.
    cr.execute("ALTER TABLE eh_credit_policy ADD COLUMN IF NOT EXISTS eh_credit_policy_limit_legacy double precision")
    cr.execute("""
        UPDATE eh_credit_policy
           SET eh_credit_policy_limit_legacy = default_credit_limit
         WHERE eh_credit_policy_limit_legacy IS NULL
    """)
