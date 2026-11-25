def migrate(cr, version):
    """Keep own letterheads: units that already filled address/phone/fax stop inheriting."""
    cr.execute(
        """
        UPDATE res_company
           SET citadel_letterhead_inherit = FALSE
         WHERE parent_id IS NOT NULL
           AND (COALESCE(citadel_letterhead_address, '') <> ''
                OR COALESCE(citadel_letterhead_address_en, '') <> ''
                OR COALESCE(citadel_letterhead_phone, '') <> ''
                OR COALESCE(citadel_letterhead_fax, '') <> '')
        """
    )
