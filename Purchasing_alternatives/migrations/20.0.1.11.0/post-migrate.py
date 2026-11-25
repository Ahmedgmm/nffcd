def migrate(cr, version):
    """payment_terms (text) was replaced by payment_term_id (drop list); it never held data."""
    cr.execute("ALTER TABLE purchase_alternative_vendor DROP COLUMN IF EXISTS payment_terms")
