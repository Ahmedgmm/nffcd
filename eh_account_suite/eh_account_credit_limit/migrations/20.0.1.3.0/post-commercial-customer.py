# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Carry credit settings to the Odoo 20 commercial customer.

Odoo 20 makes the topmost parent the commercial partner; Odoo 19 stopped at
the first company. A subsidiary that was its own commercial customer keeps
its stored limit and policy, but the credit gate now reads its topmost
parent, so the settings would silently stop applying. Move them to the
customer that now governs the subsidiary, never loosening what governs it,
and record every moved or displaced value there for manager review.
"""

import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        SELECT id
          FROM res_partner
         WHERE commercial_partner_id IS NOT NULL
           AND commercial_partner_id != id
           AND (eh_credit_limit IS NOT NULL
                OR eh_credit_policy_id IS NOT NULL)
        """
    )
    partner_ids = [row[0] for row in cr.fetchall()]
    if not partner_ids:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    handled = env['res.partner'].browse(
        partner_ids,
    )._eh_relocate_demoted_credit_config(apply=True)
    _logger.warning(
        "Credit limit 20.0: %d partner(s) are no longer their own commercial "
        "customer; their credit settings were carried to the customer that "
        "governs them where that does not loosen its terms, and every value "
        "is recorded on that customer for manager review.",
        handled,
    )
