# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Keep signed B2B mandates eligible after Odoo 20 re-derives is_company.

Odoo 19 let a user flag a debtor as a company; Odoo 20 computes is_company
as a top level partner with a VAT number. A B2B mandate signed and activated
under Odoo 19 already proved a business debtor, so it records that proof on
the mandate itself instead of failing at the next batch confirm or export
once the debtor's company flag is recomputed.
"""


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE eh_sepa_mandate
           SET b2b_business_debtor_confirmed = TRUE
         WHERE local_instrument = 'B2B'
           AND state != 'draft'
           AND b2b_business_debtor_confirmed IS NOT TRUE
    """)
