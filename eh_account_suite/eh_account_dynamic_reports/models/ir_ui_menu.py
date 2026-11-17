"""Prefer available dynamic reports while retaining legacy reports in debug."""
from odoo import api, models


# Match report menus explicitly: tax, daily books and annual reports have no
# equivalent here and must remain available.
LEGACY_REPORTS = {
    'menu_profit_and_loss': ('menu_account_report_pl',),
    'menu_balance_sheet': ('menu_account_report_bs',),
    'menu_trial_balance': ('menu_general_balance_report',),
    'menu_general_ledger': ('menu_general_ledger',),
    'menu_partner_ledger': ('menu_partner_ledger',),
    'menu_aged_receivable': ('menu_aged_receivable',),
    'menu_aged_payable': ('menu_aged_payable',),
    'menu_cash_flow': ('menu_account_report_cash_flow',),
}


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    @api.ormcache('frozenset(self.env.user._get_group_ids())', 'debug')
    def _visible_menu_ids(self, debug=False):
        visible = super()._visible_menu_ids(debug=debug)
        if debug:
            return visible

        def available(xmlid):
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            return menu if menu and menu.id in visible else self.browse()

        hidden = self.browse()
        for dynamic, legacy_names in LEGACY_REPORTS.items():
            if available(f'eh_account_dynamic_reports.{dynamic}'):
                for legacy in legacy_names:
                    hidden |= available(f'accounting_pdf_reports.{legacy}')
        if all(available(f'eh_account_dynamic_reports.menu_aged_{kind}')
               for kind in ('receivable', 'payable')):
            hidden |= available('accounting_pdf_reports.menu_aged_trial_balance')

        remaining = set(visible) - set(hidden.ids)
        # Remove folders emptied by hiding their reports, preserving folders
        # that still contain a unique report or another accessible action.
        parents = hidden.sudo().parent_id
        while parents:
            empty = parents.filtered(
                lambda menu: not menu.action
                and not any(child.id in remaining for child in menu.child_id)
            )
            remaining.difference_update(empty.ids)
            parents = empty.parent_id
        return frozenset(remaining)
