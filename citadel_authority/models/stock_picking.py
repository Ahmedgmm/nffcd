from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockWarehouse(models.Model):
    _inherit = "stock.warehouse"

    citadel_receipt_manager_id = fields.Many2one(
        "res.users", string="مسؤول المخزن (اعتماد الاستلام)",
        domain="[('share', '=', False), ('company_ids', 'in', company_id)]",
        help="المستخدم الوحيد الذي يمكنه تأكيد الاستلامات الخاضعة للجنة الفحص والاستلام بعد اعتماد أعضائها.",
    )


class StockPicking(models.Model):
    _name = "stock.picking"
    _inherit = ["stock.picking", "citadel.authority.mixin"]

    _citadel_guard_fields = {"citadel_committee_employee_ids", "partner_id", "picking_type_id"}

    citadel_committee_employee_ids = fields.Many2many(
        "hr.employee", "citadel_picking_committee_employee_rel", "picking_id", "employee_id",
        string="لجنة الفحص والاستلام", copy=True,
    )
    citadel_receipt_manager_id = fields.Many2one(
        "res.users", string="مسؤول المخزن", compute="_compute_citadel_receipt_manager",
    )
    citadel_receipt_can_validate = fields.Boolean(compute="_compute_citadel_receipt_can_validate")

    @api.depends("picking_type_id.warehouse_id.citadel_receipt_manager_id")
    def _compute_citadel_receipt_manager(self):
        for picking in self:
            picking.citadel_receipt_manager_id = picking.sudo().picking_type_id.warehouse_id.citadel_receipt_manager_id

    @api.depends_context("uid")
    @api.depends("citadel_committee_employee_ids", "citadel_authority_request_id.state")
    def _compute_citadel_receipt_can_validate(self):
        for picking in self:
            if not picking._citadel_authority_committee_required():
                picking.citadel_receipt_can_validate = True
                continue
            picking.citadel_receipt_can_validate = (
                not picking.citadel_authority_requires_approval
                and (self.env.su or picking.citadel_receipt_manager_id == self.env.user)
            )

    # ------------------------------------------------------------------
    # Authority integration
    # ------------------------------------------------------------------
    def _citadel_authority_document_type(self):
        return "stock_receipt"

    def _citadel_authority_committee_users(self):
        return self.sudo().citadel_committee_employee_ids.user_id.with_env(self.env)

    def _citadel_authority_committee_required(self):
        self.ensure_one()
        return self.picking_type_code == "incoming" and bool(self.citadel_committee_employee_ids)

    def _citadel_authority_matching_policy(self, create=True):
        self.ensure_one()
        if self.picking_type_code != "incoming":
            return self.env["citadel.authority.policy"], 0.0
        return super()._citadel_authority_matching_policy(create=create)

    def _citadel_authority_amount(self):
        self.ensure_one()
        purchase_lines = self.move_ids.purchase_line_id
        return sum(
            move.purchase_line_id.price_unit * move.product_uom_qty
            for move in self.move_ids if move.purchase_line_id
        ) if purchase_lines else 0.0

    def _citadel_authority_currency(self):
        self.ensure_one()
        return self.move_ids.purchase_line_id.order_id.currency_id[:1] or self.company_id.currency_id

    def _citadel_authority_date(self):
        return self.scheduled_date.date() if self.scheduled_date else fields.Date.context_today(self)

    def _citadel_authority_requester(self):
        self.ensure_one()
        order = self.sudo().move_ids.purchase_line_id.order_id[:1]
        return order.user_id or order.create_uid or self.create_uid

    def _citadel_authority_fingerprint_values(self):
        self.ensure_one()
        return {
            **super()._citadel_authority_fingerprint_values(),
            "partner_id": self.partner_id.id,
            "picking_type_id": self.picking_type_id.id,
            "committee": sorted(self.citadel_committee_employee_ids.ids),
            "moves": [
                [move.product_id.id, move.product_uom_qty, move.quantity, move.uom_id.id]
                for move in self.move_ids.filtered(lambda item: item.state != "cancel").sorted("id")
            ],
        }

    def _citadel_check_receipt_manager(self):
        for picking in self:
            if not picking._citadel_authority_committee_required() or self.env.su:
                continue
            manager = picking.citadel_receipt_manager_id
            if not manager:
                raise UserError(_(
                    "Set the receipt manager on warehouse %s before validating committee receipts.",
                    picking.picking_type_id.warehouse_id.display_name,
                ))
            if manager != self.env.user:
                raise UserError(_(
                    "Only the warehouse receipt manager %(manager)s may validate %(picking)s.",
                    manager=manager.display_name, picking=picking.display_name,
                ))

    def _citadel_start_receipt_approval(self):
        for picking in self.sudo():
            if picking.state in ("done", "cancel") or not picking._citadel_authority_committee_required():
                continue
            if not picking.move_ids.filtered(lambda move: move.state not in ("done", "cancel")):
                continue
            picking.with_user(self.env.user)._citadel_authority_start(require_policy=True)

    def action_citadel_print_receipt_committee(self):
        return self.env.ref("citadel_authority.action_report_receipt_committee").report_action(self)

    def _citadel_receipt_day_and_date(self):
        from .purchase_committee import arabic_day_and_date
        self.ensure_one()
        return arabic_day_and_date(fields.Date.context_today(self, self.date_done) if self.date_done else False)

    def _citadel_report_lang(self):
        return "ar_001" if self.env["res.lang"]._lang_get("ar_001") else self.env.lang

    def button_validate(self):
        if self.env.context.get("citadel_business_action"):
            return super().button_validate()
        governed = self.filtered(
            lambda picking: picking.picking_type_code == "incoming" and picking.state not in ("done", "cancel")
        )
        governed._citadel_check_receipt_manager()
        allowed = governed.filtered(lambda picking: picking._citadel_authority_gate())
        (governed - allowed)._citadel_authority_notify_blocked()
        actionable = (self - governed) | allowed
        if not actionable:
            return True
        result = super(StockPicking, actionable.with_context(citadel_business_action=True)).button_validate()
        allowed.filtered(lambda picking: picking.state == "done")._citadel_authority_complete()
        return result

    def _create_backorder(self, backorder_moves=None, from_manual_backorder=False):
        backorders = super()._create_backorder(backorder_moves=backorder_moves, from_manual_backorder=from_manual_backorder)
        backorders._citadel_start_receipt_approval()
        return backorders

    def action_cancel(self):
        result = super().action_cancel()
        self.filtered(lambda picking: picking.state == "cancel")._citadel_authority_cancel_open()
        return result
