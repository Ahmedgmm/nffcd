from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

ARABIC_WEEKDAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


def arabic_day_and_date(value):
    """Return ('الأحد', '24/11/2026') for official minutes."""
    if not value:
        return "", ""
    return ARABIC_WEEKDAYS[value.weekday()], value.strftime("%d/%m/%Y")


class CitadelPurchasePricingCommittee(models.Model):
    _name = "citadel.purchase.pricing.committee"
    _description = "Purchase Pricing Committee"
    _inherit = ["mail.thread"]
    _order = "id desc"
    _check_company_auto = True

    name = fields.Char(string="رقم المحضر", required=True, readonly=True, copy=False, default=lambda self: _("New"))
    order_id = fields.Many2one(
        "purchase.order", string="طلب الشراء", required=True, ondelete="cascade", index=True, check_company=True,
    )
    company_id = fields.Many2one(related="order_id.company_id", store=True, readonly=True, string="الشركة")
    date = fields.Date(string="تاريخ انعقاد اللجنة", required=True, default=fields.Date.context_today, tracking=True)
    employee_ids = fields.Many2many(
        "hr.employee", "citadel_pricing_committee_employee_rel", "committee_id", "employee_id",
        string="أعضاء اللجنة", required=True, tracking=True,
        domain="[('company_id', '=', company_id)]",
    )
    chairman_id = fields.Many2one(
        "hr.employee", string="رئيس اللجنة", tracking=True,
        domain="[('id', 'in', employee_ids)]",
        help="يظهر أولاً في المحضر. إن تُرك فارغاً يُعتبر أول عضو رئيساً.",
    )
    purpose = fields.Text(
        string="الغرض", default="تقدير القيمة السوقية العادلة للأصناف الواردة بطلب الشراء",
    )
    signed_attachment_ids = fields.Many2many(
        "ir.attachment", "citadel_pricing_committee_attachment_rel", "committee_id", "attachment_id",
        string="المحضر الموقّع (نسخة ممسوحة)",
    )

    @api.constrains("employee_ids", "chairman_id", "order_id")
    def _check_members(self):
        for committee in self:
            self.env["citadel.authority.mixin"]._citadel_check_committee_employees(
                committee.employee_ids, committee.company_id, need_users=False,
            )
            if committee.chairman_id and committee.chairman_id not in committee.employee_ids:
                raise ValidationError(_("The chairman must be one of the committee members."))

    @api.model_create_multi
    def create(self, vals_list):
        committees = super().create(vals_list)
        for committee in committees:
            if committee.order_id.state not in ("draft", "sent"):
                raise UserError(_("Pricing committees can only be formed for draft orders."))
            if committee.name == _("New"):
                count = len(committee.order_id.citadel_pricing_committee_ids)
                committee.name = "%s-PC%s" % (committee.order_id.name, count)
            committee.order_id.message_post(body=_(
                "Pricing committee %(name)s formed on %(date)s: %(members)s",
                name=committee.name, date=committee.date,
                members=", ".join(committee._citadel_ordered_members().mapped("name")),
            ))
        return committees

    def write(self, vals):
        if self.filtered(lambda committee: committee.order_id.state not in ("draft", "sent")) and set(vals) - {
            "signed_attachment_ids", "message_main_attachment_id",
        }:
            raise UserError(_("The pricing committee of a confirmed order cannot be changed."))
        return super().write(vals)

    def _citadel_ordered_members(self):
        self.ensure_one()
        chairman = self.chairman_id or self.employee_ids.sorted("name")[:1]
        return chairman | (self.employee_ids - chairman).sorted("name")

    def _citadel_report_lines(self):
        self.ensure_one()
        return self.order_id.order_line.filtered(lambda line: not line.display_type and line.product_id)

    def _citadel_day_and_date(self):
        self.ensure_one()
        return arabic_day_and_date(self.date)

    def _citadel_report_lang(self):
        return "ar_001" if self.env["res.lang"]._lang_get("ar_001") else self.env.lang

    def action_print(self):
        self.ensure_one()
        return self.env.ref("citadel_authority.action_report_pricing_committee").report_action(self)

    def action_save_and_print(self):
        return self.action_print()


class CitadelPurchaseReceiptCommitteeWizard(models.TransientModel):
    _name = "citadel.purchase.receipt.committee.wizard"
    _description = "Select Receipt Committee"

    order_id = fields.Many2one("purchase.order", required=True, readonly=True)
    company_id = fields.Many2one(related="order_id.company_id")
    next_step = fields.Selection(
        [("confirm", "Confirm"), ("request", "Request approval"), ("none", "Save only")], default="none",
    )
    employee_ids = fields.Many2many(
        "hr.employee", string="أعضاء لجنة الفحص والاستلام",
        domain="[('company_id', '=', company_id)]",
    )
    warehouse_id = fields.Many2one(related="order_id.picking_type_id.warehouse_id", string="المخزن المستلم")
    manager_id = fields.Many2one(related="order_id.citadel_receipt_manager_id", string="مسؤول المخزن (يؤكد الاستلام)")

    def action_apply(self):
        self.ensure_one()
        order = self.order_id
        if order.state not in ("draft", "sent"):
            raise UserError(_("The receipt committee can only be changed on draft orders."))
        if not order.citadel_receipt_manager_id:
            raise UserError(_(
                "Set the receipt manager on warehouse %s first.", order.picking_type_id.warehouse_id.display_name or "-",
            ))
        self.env["citadel.authority.mixin"]._citadel_check_committee_employees(
            self.employee_ids, order.company_id, excluded_users=order._citadel_receipt_excluded_users(),
        )
        order.write({"citadel_receipt_committee_employee_ids": [(6, 0, self.employee_ids.ids)]})
        if self.next_step == "confirm":
            result = order.button_confirm()
        elif self.next_step == "request":
            result = order.action_citadel_request_approval()
        else:
            result = True
        if isinstance(result, dict):
            return result
        return {"type": "ir.actions.act_window_close"}
