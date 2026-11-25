from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    alternative_comparison_ids = fields.One2many(
        "purchase.alternative.comparison",
        "order_id",
        string="Alternative Comparisons",
        copy=False,
    )
    alternative_comparison_count = fields.Integer(
        string="Alternative Generator",
        compute="_compute_alternative_comparison_count",
    )
    alternative_source_comparison_id = fields.Many2one(
        "purchase.alternative.comparison",
        string="مقارنة العروض المصدر",
        copy=False,
        readonly=True,
        index=True,
        help="RFQ created from an alternatives comparison; it needs that committee decision approved.",
    )

    def _compute_alternative_comparison_count(self):
        for order in self:
            order.alternative_comparison_count = len(order.alternative_comparison_ids)

    def _get_or_create_alternative_comparison(self):
        self.ensure_one()
        comparison = self.alternative_comparison_ids[:1]
        if not comparison:
            comparison = self.env["purchase.alternative.comparison"].create_from_order(self)
        else:
            comparison.sync_from_order()
        return comparison

    def _alternative_table_action(self, comparison):
        return {
            "type": "ir.actions.client",
            "tag": "purchase_alternative_table",
            "name": _("Alternative Generator"),
            "params": {
                "comparison_id": comparison.id,
            },
        }

    def action_open_alternative_generator(self):
        self.ensure_one()
        comparison = self.alternative_comparison_ids[:1]
        if not comparison:
            if self.state not in ("draft", "sent"):
                raise UserError(_("Alternatives can only be created for draft RFQs."))
            return {
                "type": "ir.actions.act_window",
                "name": _("لجنة البت والمفاضلة"),
                "res_model": "purchase.alternative.committee.wizard",
                "view_mode": "form",
                "target": "new",
                "context": {"default_order_id": self.id},
            }
        comparison.sync_from_order()
        return self._alternative_table_action(comparison)

    def _citadel_purchase_prerequisites(self):
        super()._citadel_purchase_prerequisites()
        for order in self:
            comparisons = order.alternative_comparison_ids | order.alternative_source_comparison_id
            for comparison in comparisons.sudo():
                if not comparison._citadel_is_used():
                    continue
                if not comparison._citadel_committee_approved():
                    raise UserError(_(
                        "%(order)s cannot be submitted or confirmed: the alternatives committee has not "
                        "approved %(comparison)s.",
                        order=order.name, comparison=comparison.name,
                    ))
                if comparison.order_id == order and comparison.state == "draft" and comparison.decision_type == "main":
                    raise UserError(_(
                        "Apply the approved committee decision in %s before confirming the order.", comparison.name,
                    ))
                if comparison.order_id == order and comparison.state == "draft" and comparison.decision_type == "split":
                    raise UserError(_(
                        "Create the approved split RFQs in %s before confirming the order.", comparison.name,
                    ))


class PurchaseAlternativeCommitteeWizard(models.TransientModel):
    _name = "purchase.alternative.committee.wizard"
    _description = "Select Alternatives Committee"

    order_id = fields.Many2one("purchase.order", required=True, readonly=True)
    company_id = fields.Many2one(related="order_id.company_id")
    employee_ids = fields.Many2many(
        "hr.employee", string="أعضاء لجنة البت والمفاضلة",
        domain="[('company_id', '=', company_id)]",
    )
    chairman_id = fields.Many2one(
        "hr.employee", string="رئيس اللجنة",
        domain="[('id', 'in', employee_ids)]",
    )

    @api.onchange("employee_ids")
    def _onchange_employee_ids_chairman(self):
        if self.chairman_id and self.chairman_id not in self.employee_ids:
            self.chairman_id = False

    def action_create(self):
        self.ensure_one()
        order = self.order_id
        comparison_model = self.env["purchase.alternative.comparison"]
        comparison_model._citadel_check_committee_employees(
            self.employee_ids, order.company_id, excluded_users=order.user_id or order.create_uid,
        )
        comparison = order.alternative_comparison_ids[:1]
        if comparison:
            comparison._check_editable()
            comparison.write({
                "citadel_committee_employee_ids": [fields.Command.set(self.employee_ids.ids)],
                "citadel_chairman_employee_id": self.chairman_id.id,
            })
        else:
            comparison = comparison_model.create_from_order(order, employees=self.employee_ids, chairman=self.chairman_id)
        return order._alternative_table_action(comparison)
