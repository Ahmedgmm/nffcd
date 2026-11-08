"""Preserve terms and quarantine conflicting native/EH credit limits."""

from odoo import SUPERUSER_ID, api
from odoo.addons.eh_account_credit_limit.migration import unify_native_credit_limits


def migrate(cr, version):
    if version:
        unify_native_credit_limits(api.Environment(cr, SUPERUSER_ID, {}))
