def migrate(cr, version):
    """Cost type was removed: a pricing committee is optional and enforced only when formed."""
    cr.execute("ALTER TABLE purchase_order DROP COLUMN IF EXISTS citadel_cost_type")
