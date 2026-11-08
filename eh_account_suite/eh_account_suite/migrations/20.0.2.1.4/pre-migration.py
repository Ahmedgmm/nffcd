"""Preserve BAS task and company progress before suite data cleanup."""

from odoo.addons.eh_account_suite.migration import transfer_bas_onboarding


def migrate(cr, version):
    if version:
        transfer_bas_onboarding(cr)
