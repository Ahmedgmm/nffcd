# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Keep the suite's sections in one Accounting app on both layouts.

navigation.py describes the two layouts. This model applies them at the
three moments Odoo changes menus behind the suite's back: a registry load
that installed or upgraded modules (the accountant module installed after
the suite, or any module update filing a section under its declared parent
again), and the deletion of the Enterprise Accounting app when accountant
is uninstalled.
"""

from odoo import api, models

from ..navigation import ENTERPRISE_ROOT, release_finance_app, sync_finance_app


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    def _register_hook(self):
        super()._register_hook()
        # Only the load that ran module data can have moved a section, and
        # the hook runs once per load, before the registry is ready. A plain
        # worker start writes nothing.
        if self.pool.updated_modules and not self.pool.ready:
            sync_finance_app(self.env)

    @api.model
    def _eh_sync_finance_app(self):
        """Apply the Enterprise layout right after the suite data loads."""
        sync_finance_app(self.env)
        return True

    def unlink(self):
        host = self.env.ref(ENTERPRISE_ROOT, raise_if_not_found=False)
        if host and host in self:
            release_finance_app(self.env, self)
        return super().unlink()
