from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .policy import DOCUMENT_TYPES


class CitadelAuthorityDelegation(models.Model):
    _name = "citadel.authority.delegation"
    _description = "Authority Delegation"
    _order = "date_start desc, id desc"

    delegator_id = fields.Many2one(
        "res.users", string="المفوِّض", required=True, default=lambda self: self.env.user,
        domain="[('share', '=', False)]", ondelete="cascade",
    )
    delegate_id = fields.Many2one(
        "res.users", string="المفوَّض إليه", required=True, domain="[('share', '=', False)]", ondelete="cascade",
    )
    scope = fields.Selection([("all", "جميع المستندات")] + DOCUMENT_TYPES, string="نطاق التفويض", required=True, default="all")
    company_id = fields.Many2one(
        "res.company", string="الشركة", required=True, default=lambda self: self.env.company,
    )
    date_start = fields.Date(string="تاريخ البداية", required=True, default=fields.Date.context_today)
    date_end = fields.Date(string="تاريخ النهاية", required=True)
    active = fields.Boolean(string="نشط", default=True)
    note = fields.Char(string="ملاحظة")

    @api.model
    def _citadel_is_manager(self):
        return self.env.user.has_group("citadel_authority.group_citadel_authority_manager")

    @api.model_create_multi
    def create(self, vals_list):
        if not self._citadel_is_manager() and any(
            vals.get("delegator_id", self.env.uid) != self.env.uid for vals in vals_list
        ):
            raise AccessError(_("You can only create your own delegations."))
        return super().create(vals_list)

    def write(self, vals):
        if not self._citadel_is_manager() and (
            any(record.delegator_id != self.env.user for record in self)
            or ("delegator_id" in vals and vals["delegator_id"] != self.env.uid)
        ):
            raise AccessError(_("You can only change your own delegations."))
        return super().write(vals)

    def unlink(self):
        if not self._citadel_is_manager() and any(record.delegator_id != self.env.user for record in self):
            raise AccessError(_("You can only remove your own delegations."))
        return super().unlink()

    @api.constrains("delegator_id", "delegate_id", "scope", "company_id", "date_start", "date_end", "active")
    def _check_delegation(self):
        for record in self:
            if record.delegator_id == record.delegate_id:
                raise ValidationError(_("You cannot delegate authority to yourself."))
            if record.delegator_id.share or record.delegate_id.share:
                raise ValidationError(_("Authority may only be delegated between internal users."))
            if record.date_end < record.date_start:
                raise ValidationError(_("The end date must be on or after the start date."))
            if record.company_id not in record.delegator_id.company_ids or record.company_id not in record.delegate_id.company_ids:
                raise ValidationError(_("Both users must have access to the delegation company."))
            overlap = self.sudo().search_count([
                ("id", "!=", record.id),
                ("active", "=", True),
                ("delegator_id", "=", record.delegator_id.id),
                ("company_id", "=", record.company_id.id),
                ("scope", "in", [record.scope, "all"] if record.scope != "all" else [item[0] for item in DOCUMENT_TYPES] + ["all"]),
                ("date_start", "<=", record.date_end),
                ("date_end", ">=", record.date_start),
            ])
            if record.active and overlap:
                raise ValidationError(_("This user already has an overlapping delegation for that scope."))
            reverse = self.sudo().search_count([
                ("active", "=", True),
                ("delegator_id", "=", record.delegate_id.id),
                ("delegate_id", "=", record.delegator_id.id),
                ("company_id", "=", record.company_id.id),
                ("date_start", "<=", record.date_end),
                ("date_end", ">=", record.date_start),
            ])
            if record.active and reverse:
                raise ValidationError(_("Circular authority delegations are not allowed."))

    @api.model
    def _citadel_active_domain(self, document_type, company):
        today = fields.Date.context_today(self)
        return [
            ("active", "=", True),
            ("scope", "in", ["all", document_type]),
            ("company_id", "=", company.id),
            ("date_start", "<=", today),
            ("date_end", ">=", today),
        ]

    @api.model
    def _citadel_delegate_for(self, principal, document_type, company):
        delegation = self.sudo().search(
            self._citadel_active_domain(document_type, company) + [("delegator_id", "=", principal.id)],
            limit=1,
        )
        return delegation.delegate_id

    @api.model
    def _citadel_principals_for(self, delegate, document_type, company):
        return self.sudo().search(
            self._citadel_active_domain(document_type, company) + [("delegate_id", "=", delegate.id)]
        ).mapped("delegator_id")

