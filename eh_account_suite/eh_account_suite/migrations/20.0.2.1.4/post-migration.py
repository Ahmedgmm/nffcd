"""Refresh global accounting workflow navigation on upgrade."""

from odoo import SUPERUSER_ID, api

from odoo.addons.eh_account_suite.navigation import refresh_suite_navigation


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    refresh_suite_navigation(env)
