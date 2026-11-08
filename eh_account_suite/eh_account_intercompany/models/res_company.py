# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ResCompany(models.Model):
    _inherit = 'res.company'

    eh_ic_consolidation_only = fields.Boolean(
        string="IC elimination output company",
        groups='eh_account_base.group_eh_manager',
        help=(
            "Reserves this non-trading company for standalone IC elimination "
            "output only. A full Group Consolidation result must use another "
            "dedicated company so eliminations are not counted twice. "
            "Inter-company elimination journals may be posted only here, "
            "never in either member company's statutory general ledger. Do "
            "not enable this on a legal entity that issues separate financial "
            "statements."
        ),
    )

    def _eh_assert_ic_output_exclusive(self):
        """Check optional consolidation references, including legacy setups."""
        if self and 'eh.consol.entity' in self.env:
            roots = self.sudo().mapped('root_id')
            scope = self.sudo().with_context(active_test=False).search([
                ('id', 'child_of', roots.ids),
            ])
            # Existing references must remain authoritative even if hidden by
            # record rules or a disabled company. Return no foreign details.
            used = self.env['eh.consol.entity'].sudo().with_context(
                active_test=False,
            ).search_count([
                ('consolidation_company_id', 'in', scope.ids),
            ], limit=1)
            if used:
                raise UserError(_(
                    "This company is reserved for full Group Consolidation "
                    "output, or shares its legal-company root. Use a separate "
                    "IC elimination output company outside that branch tree "
                    "to avoid counting the same elimination twice. Existing "
                    "records are retained; reset or reverse conflicting "
                    "output through its original workflow before reconfiguration."
                ))

    def _eh_reserve_ic_output_scope(self):
        if self and 'eh.consol.entity' in self.env:
            roots = self.sudo().mapped('root_id')
            roots.flush_recordset(['eh_ic_consolidation_only'])
            for root_id in sorted(roots.ids):
                # Same MVCC barrier as consolidation assignment. Acquire the
                # root before write() touches a branch row to keep lock order.
                self.env.cr.execute(
                    'UPDATE res_company '
                    'SET eh_ic_consolidation_only = eh_ic_consolidation_only '
                    'WHERE id = %s', (root_id,),
                )

    @api.constrains('eh_ic_consolidation_only')
    def _check_ic_output_exclusive(self):
        # Inspect only protected ownership metadata; ordinary company admins
        # need not belong to the EH manager group to create a normal branch.
        companies = self.sudo().filtered('eh_ic_consolidation_only')
        # Flush before querying references: this company-row write conflicts
        # with consolidation's reservation barrier. A stale Repeatable Read
        # transaction receives the normal serialization retry, never a false
        # empty result from a snapshot taken before the competing reservation.
        companies.flush_recordset(['eh_ic_consolidation_only'])
        companies._eh_reserve_ic_output_scope()
        companies._eh_assert_ic_output_exclusive()

    def write(self, vals):
        if 'eh_ic_consolidation_only' in vals and not vals['eh_ic_consolidation_only']:
            used = self.env['eh.ic.elimination.batch'].sudo().search([
                ('elimination_company_id', 'in', self.ids),
                '|', ('move_history_ids', '!=', False),
                ('state', 'in', ('computed', 'posted')),
            ], limit=1)
            if used:
                raise UserError(_(
                    "This company cannot be converted back to a trading/legal-entity "
                    "workspace while a computed elimination batch or posted "
                    "elimination history still depends on it."
                ))
        if 'eh_ic_consolidation_only' in vals:
            self._eh_reserve_ic_output_scope()
        return super().write(vals)
