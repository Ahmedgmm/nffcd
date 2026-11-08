from odoo import _, api, models

from .policy import DOCUMENT_TYPES


DASHBOARD_BLOCKS = {
    "purchase_order": ("fa-shopping-cart", "teal"),
    "sale_order": ("fa-line-chart", "purple"),
    "vendor_bill": ("fa-file-text-o", "coral"),
    "customer_invoice": ("fa-file-text", "amber"),
    "vendor_refund": ("fa-reply", "coral"),
    "customer_credit_note": ("fa-reply-all", "amber"),
    "journal_entry": ("fa-book", "teal"),
    "payment": ("fa-credit-card", "purple"),
}


def _initials(name):
    return "".join(part[0] for part in (name or "?").split()[:2]).upper()


class CitadelAuthorityDashboard(models.AbstractModel):
    _name = "citadel.authority.dashboard"
    _description = "Authority Dashboard"

    @api.model
    def get_dashboard_data(self):
        """Return the authority matrix as flows the dashboard can draw."""
        company = self.env.company
        policy_model = self.env["citadel.authority.policy"]
        policies = policy_model.sudo().search([
            ("company_id", "in", policy_model._citadel_company_chain(company).ids),
            ("active", "=", True),
        ])
        requests = self.env["citadel.authority.request"].search([("company_id", "=", company.id)])
        waiting = requests.filtered(lambda request: request.state == "pending" and request.can_approve)
        blocks = []
        for document_type, label in DOCUMENT_TYPES:
            scoped_policies = policies.filtered(lambda policy: policy.document_type == document_type)
            scoped_requests = requests.filtered(lambda request: request.document_type == document_type)
            icon, color = DASHBOARD_BLOCKS[document_type]
            blocks.append({
                "key": document_type,
                "label": label,
                "icon": icon,
                "color": color,
                "policies": len(scoped_policies),
                "pending": len(scoped_requests.filtered(lambda request: request.state == "pending")),
                "waiting": len(waiting.filtered(lambda request: request.document_type == document_type)),
                "flows": [policy._citadel_dashboard_flow() for policy in scoped_policies],
            })
        return {
            "company": company.display_name,
            "is_manager": self.env.user.has_group("citadel_authority.group_citadel_authority_manager"),
            "blocks": blocks,
            "totals": {
                "policies": len(policies),
                "pending": len(requests.filtered(lambda request: request.state == "pending")),
                "waiting": len(waiting),
            },
        }


class CitadelAuthorityPolicy(models.Model):
    _inherit = "citadel.authority.policy"

    def _citadel_dashboard_flow(self):
        self.ensure_one()
        currency = self.currency_id.symbol or self.currency_id.name
        amount_band = _("أي مبلغ")
        if self.min_amount and self.max_amount:
            amount_band = _("%(minimum)s – %(maximum)s %(currency)s", minimum=f"{self.min_amount:,.0f}", maximum=f"{self.max_amount:,.0f}", currency=currency)
        elif self.min_amount:
            amount_band = _("من %(minimum)s %(currency)s", minimum=f"{self.min_amount:,.0f}", currency=currency)
        elif self.max_amount:
            amount_band = _("حتى %(maximum)s %(currency)s", maximum=f"{self.max_amount:,.0f}", currency=currency)
        steps = [step._citadel_dashboard_step() for step in self.step_ids.sorted(lambda step: (step.sequence, step.id))]
        controls = []
        if not self.allow_self_approval:
            controls.append(_("لا يجوز لمقدم الطلب الاعتماد"))
        if not self.allow_same_user_multiple_steps:
            controls.append(_("شخص واحد لكل خطوة اعتماد"))
        return {
            "id": self.id,
            "name": self.display_name,
            "amount_band": amount_band,
            "domain": self.domain if self.domain not in ("[]", "") else _("جميع المستندات"),
            "controls": " · ".join(controls),
            "steps": steps,
        }


class CitadelAuthorityPolicyStep(models.Model):
    _inherit = "citadel.authority.policy.step"

    def _citadel_dashboard_step(self):
        self.ensure_one()
        role = self.role_id
        if role.resolver == "manager":
            holders = self.env["res.users"]
            holder_text = _("المدير المباشر لمقدم الطلب")
            badge = "M"
        else:
            holders = role.group_id.sudo().all_user_ids if role.resolver == "group" else role.user_ids
            holders = holders.filtered(lambda user: user.active and not user.share and self.company_id in user.company_ids)
            holder_text = ", ".join(holders.mapped("name")) or _("لا يوجد صاحب صلاحية مؤهل")
            badge = _initials(holders.name) if len(holders) == 1 else str(len(holders) or "!")
        mode = {
            "any": _("أي شخص"),
            "all": _("الجميع"),
            "quorum": _("النصاب"),
        }[self.approval_mode]
        subtitle = mode if self.action == "approve" else _("للعلم")
        if self.approval_mode == "quorum" and self.action == "approve":
            subtitle = _("%(mode)s (المطلوب: %(count)s)", mode=mode, count=self.required_approvals)
        return {
            "role_name": role.display_name,
            "badge": badge,
            "subtitle": subtitle,
            "holders": holder_text,
            "is_inform": self.action == "inform",
            "warning": not holders and role.resolver != "manager",
        }

