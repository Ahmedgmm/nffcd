# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Re-key open cases on the Odoo 20 commercial customer.

Odoo 20 makes the topmost parent the commercial partner; Odoo 19 stopped at
the first company. An open case of a subsidiary that was its own commercial
customer would otherwise stay open next to a new case the auto creator opens
for the parent, and both would be followed up.
"""

import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    handled = env['eh.collections.case']._eh_rehome_demoted_cases()
    if handled:
        _logger.warning(
            "Collections 20.0: %d open case(s) belonged to a customer that is "
            "no longer its own commercial customer and were moved to, or "
            "resolved into, the commercial customer's case.",
            handled,
        )
