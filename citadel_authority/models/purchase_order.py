from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    _name = "purchase.order"
    _inherit = ["purchase.order", "citadel.authority.mixin"]

    _citadel_guard_fields = {
        "company_id", "partner_id", "currency_id", "date_order", "order_line",
        "payment_term_id", "fiscal_position_id", "user_id",
        "citadel_cost_type", "citadel_receipt_committee_employee_ids", "picking_type_id",
    }

    citadel_cost_type = fields.Selection(
        [("known", "تكلفة معروفة"), ("unknown", "تكلفة غير معروفة (لجنة تسعير)")],
        string="نوع التكلفة", required=True, default="known", tracking=True, copy=True,
    )
    citadel_requester_employee_id = fields.Many2one(
        "hr.employee", string="طالب الشراء", tracking=True, check_company=True,
        default=lambda self: self.env.user.employee_ids.filtered(lambda employee: employee.company_id == self.env.company)[:1],
        domain="[('company_id', '=', company_id)]",
    )
    citadel_request_department_id = fields.Many2one(
        "hr.department", string="القسم الطالب للشراء", tracking=True, check_company=True,
        compute="_compute_citadel_request_department", store=True, readonly=False, precompute=True,
        help="يُملأ تلقائياً من قسم طالب الشراء، ويمكن تعديله. يُطبع في خانة «القسم الطالب للشراء».",
    )
    citadel_purchase_purpose = fields.Char(string="الغرض من الشراء", tracking=True)
    citadel_purchase_method = fields.Selection(
        [
            ("public_tender", "مناقصة عامة"),
            ("limited_tender", "مناقصة محدودة"),
            ("practice", "ممارسة"),
            ("direct", "الأمر المباشر"),
        ],
        string="طريقة الشراء", tracking=True,
    )
    citadel_estimated_amount = fields.Monetary(
        string="القيمة التقديرية", currency_field="currency_id", tracking=True,
        help="تظهر في طلب الشراء. إن تُركت صفراً تُستخدم قيمة الأمر قبل الضرائب عند توفرها.",
    )
    citadel_pricing_committee_ids = fields.One2many(
        "citadel.purchase.pricing.committee", "order_id", string="لجان التسعير", copy=False,
    )
    citadel_pricing_committee_count = fields.Integer(compute="_compute_citadel_pricing_committee_count")
    citadel_receipt_committee_employee_ids = fields.Many2many(
        "hr.employee", "citadel_po_receipt_committee_employee_rel", "order_id", "employee_id",
        string="لجنة الفحص والاستلام", copy=False, tracking=True,
    )
    citadel_receipt_manager_id = fields.Many2one(
        "res.users", string="مسؤول المخزن", compute="_compute_citadel_receipt_manager",
    )
    citadel_needs_receipt_committee = fields.Boolean(compute="_compute_citadel_needs_receipt_committee")

    @api.depends("citadel_requester_employee_id")
    def _compute_citadel_request_department(self):
        for order in self:
            department = order.citadel_requester_employee_id.sudo().department_id
            if department:
                order.citadel_request_department_id = department

    @api.depends("citadel_pricing_committee_ids")
    def _compute_citadel_pricing_committee_count(self):
        for order in self:
            order.citadel_pricing_committee_count = len(order.citadel_pricing_committee_ids)

    @api.depends("picking_type_id.warehouse_id.citadel_receipt_manager_id")
    def _compute_citadel_receipt_manager(self):
        for order in self:
            order.citadel_receipt_manager_id = order.sudo().picking_type_id.warehouse_id.citadel_receipt_manager_id

    @api.depends("order_line.product_id.type", "picking_type_id.warehouse_id.citadel_receipt_manager_id")
    def _compute_citadel_needs_receipt_committee(self):
        """Warehouses opt in by naming a receipt manager; goods received there need a committee."""
        for order in self:
            order.citadel_needs_receipt_committee = bool(order.citadel_receipt_manager_id) and any(
                product.type == "consu" for product in order.order_line.product_id
            )

    # ------------------------------------------------------------------
    # Purchase workflow prerequisites
    # ------------------------------------------------------------------
    def _citadel_purchase_prerequisites(self):
        """Raise when the order is not ready to be submitted or confirmed."""
        for order in self:
            if order.citadel_cost_type != "unknown":
                continue
            committee = order.citadel_pricing_committee_ids.sorted("id", reverse=True)[:1]
            if not committee:
                raise UserError(_("%s has an unknown cost: form a pricing committee first.", order.name))
            if not committee.signed_attachment_ids:
                raise UserError(_(
                    "Attach the signed pricing committee minutes %(committee)s to %(order)s first.",
                    committee=committee.name, order=order.name,
                ))
            unpriced = order.order_line.filtered(
                lambda line: not line.display_type and line.product_id and line.price_unit <= 0
            )
            if unpriced:
                raise UserError(_(
                    "Enter the committee prices on %(order)s for: %(products)s",
                    order=order.name, products=", ".join(unpriced.product_id.mapped("display_name")),
                ))

    def _citadel_receipt_committee_missing(self):
        return self.filtered(
            lambda order: order.citadel_needs_receipt_committee and not order.citadel_receipt_committee_employee_ids
        )

    def _citadel_receipt_excluded_users(self):
        self.ensure_one()
        return self._citadel_authority_requester() | self.citadel_receipt_manager_id

    def _citadel_check_receipt_committee(self):
        for order in self.filtered("citadel_receipt_committee_employee_ids"):
            if not order.citadel_receipt_manager_id:
                raise UserError(_(
                    "Set the receipt manager on warehouse %s first.",
                    order.picking_type_id.warehouse_id.display_name or "-",
                ))
            self._citadel_check_committee_employees(
                order.citadel_receipt_committee_employee_ids, order.company_id,
                excluded_users=order._citadel_receipt_excluded_users(),
            )

    def _citadel_receipt_committee_action(self, next_step):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("لجنة الفحص والاستلام"),
            "res_model": "citadel.purchase.receipt.committee.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_order_id": self.id,
                "default_next_step": next_step,
                "default_employee_ids": self.citadel_receipt_committee_employee_ids.ids,
            },
        }

    def _citadel_prepare_submission(self, next_step):
        """Run the checks; return a wizard action when the receipt committee is missing."""
        candidates = self.filtered(lambda order: order.state in ("draft", "sent"))
        candidates._citadel_purchase_prerequisites()
        missing = candidates._citadel_receipt_committee_missing()
        if missing:
            if len(self) == 1:
                return self._citadel_receipt_committee_action(next_step)
            raise UserError(_(
                "Select the receipt committee on each order first: %s", ", ".join(missing.mapped("name")),
            ))
        candidates._citadel_check_receipt_committee()
        return False

    def action_open_pricing_committee(self):
        self.ensure_one()
        if self.state not in ("draft", "sent"):
            raise UserError(_("Pricing committees can only be formed for draft orders."))
        return {
            "type": "ir.actions.act_window",
            "name": _("لجنة تسعير"),
            "res_model": "citadel.purchase.pricing.committee",
            "view_mode": "form",
            "target": "new",
            "context": {"default_order_id": self.id},
        }

    def action_view_pricing_committees(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("لجان التسعير"),
            "res_model": "citadel.purchase.pricing.committee",
            "view_mode": "list,form",
            "domain": [("order_id", "=", self.id)],
            "context": {"default_order_id": self.id},
        }

    def action_open_receipt_committee(self):
        self.ensure_one()
        return self._citadel_receipt_committee_action("none")

    def action_citadel_request_approval(self):
        action = self._citadel_prepare_submission("request")
        if action:
            return action
        return super().action_citadel_request_approval()

    def _citadel_assign_receipt_committee(self):
        for order in self.filtered("citadel_receipt_committee_employee_ids"):
            pickings = order.sudo().picking_ids.filtered(
                lambda picking: picking.picking_type_code == "incoming"
                and picking.state not in ("done", "cancel")
                and not picking.citadel_committee_employee_ids
            )
            if not pickings:
                continue
            pickings.with_context(citadel_skip_invalidation=True).write({
                "citadel_committee_employee_ids": [(6, 0, order.citadel_receipt_committee_employee_ids.ids)],
            })
            pickings.with_user(self.env.user)._citadel_start_receipt_approval()

    def button_approve(self, force=False):
        result = super().button_approve(force=force)
        self.filtered(lambda order: order.state == "purchase")._citadel_assign_receipt_committee()
        return result

    def _citadel_report_lang(self):
        return "ar_001" if self.env["res.lang"]._lang_get("ar_001") else self.env.lang

    # ------------------------------------------------------------------
    # Purchase request (طلب شراء) printout
    # ------------------------------------------------------------------
    def _citadel_request_lines(self):
        self.ensure_one()
        return self.order_line.filtered(lambda line: not line.display_type and line.product_id)

    def _citadel_stock_balance(self, line):
        """Text for the 'رصيد المخزن' column: on-hand quantity in the receiving warehouse."""
        product = line.product_id
        if product.type != "consu" or not getattr(product, "is_storable", True):
            return "-"
        warehouse = self.sudo().picking_type_id.warehouse_id
        quantity = product.sudo().with_context(warehouse_id=warehouse.id).qty_available if warehouse else 0.0
        if line.uom_id and product.uom_id and line.uom_id != product.uom_id:
            quantity = product.uom_id._compute_quantity(quantity, line.uom_id)
        return "لا يوجد" if not quantity else "%g" % round(quantity, 2)

    def _citadel_line_notes(self, line):
        name = (line.name or "").strip()
        product_name = line.product_id.display_name or ""
        return "" if not name or name == product_name or name in product_name else name

    def _citadel_estimated_value(self):
        self.ensure_one()
        return self.citadel_estimated_amount or self.amount_untaxed

    def _citadel_request_date(self):
        self.ensure_one()
        value = self.create_date or self.date_order
        return fields.Date.context_today(self, value).strftime("%d/%m/%Y") if value else ""

    def _citadel_report_info(self):
        """Purchase-request header shared by the request and committee minutes."""
        self.ensure_one()
        requester = self._citadel_authority_requester()
        employee = self.citadel_requester_employee_id.sudo() or requester.sudo().employee_ids.filtered(
            lambda item: item.company_id == self.company_id
        )[:1]
        department = self.citadel_request_department_id or employee.department_id
        return {
            "department": department.name or "",
            "requester": employee.name or requester.name or "",
            "purpose": self.citadel_purchase_purpose or "",
            "method": dict(self._fields["citadel_purchase_method"].selection).get(self.citadel_purchase_method, ""),
            "estimated": self._citadel_estimated_value(),
            "date": self._citadel_request_date(),
        }

    def _citadel_report_committees(self):
        """Members for the 'تشكيل اللجان' section: pricing committee and alternatives committee."""
        self.ensure_one()
        pricing = self.citadel_pricing_committee_ids.sorted("id", reverse=True)[:1]
        pricing_members = pricing._citadel_ordered_members() if pricing else self.env["hr.employee"]
        evaluation_members = self.env["hr.employee"]
        if "alternative_comparison_ids" in self._fields:
            comparison = (self.alternative_comparison_ids | self.alternative_source_comparison_id)[:1]
            evaluation_members = comparison.sudo().citadel_committee_employee_ids.sorted("name")
        return pricing_members, evaluation_members

    def action_citadel_print_purchase_request(self):
        return self.env.ref("citadel_authority.action_report_purchase_request").report_action(self)
    _citadel_amount_fields = {"order_line", "currency_id"}

    def _citadel_authority_document_type(self):
        return "purchase_order"

    def _citadel_authority_amount(self):
        self.ensure_one()
        return abs(self.amount_total)

    def _citadel_authority_currency(self):
        return self.currency_id

    def _citadel_authority_date(self):
        return self.date_order.date() if self.date_order else fields.Date.context_today(self)

    def _citadel_authority_requester(self):
        return self.user_id or self.create_uid

    def _citadel_authority_manager_users(self):
        return self.sudo().user_id.employee_id.parent_id.user_id

    def _citadel_authority_fingerprint_values(self):
        self.ensure_one()
        return {
            **super()._citadel_authority_fingerprint_values(),
            "partner_id": self.partner_id.id,
            "currency_id": self.currency_id.id,
            "date_order": fields.Datetime.to_string(self.date_order) if self.date_order else False,
            "cost_type": self.citadel_cost_type,
            "receipt_committee": sorted(self.citadel_receipt_committee_employee_ids.ids),
            "picking_type_id": self.picking_type_id.id,
            "lines": [
                [line.product_id.id, line.product_qty, line.uom_id.id, line.price_unit, sorted(line.tax_ids.ids)]
                for line in self.order_line.sorted(lambda item: (item.sequence, item.id))
            ],
        }

    def button_confirm(self):
        if not self.env.context.get("citadel_business_action"):
            action = self._citadel_prepare_submission("confirm")
            if action:
                return action
        candidates = self.filtered(lambda order: order.state in ("draft", "sent"))
        allowed = candidates.filtered(lambda order: order._citadel_authority_gate())
        (candidates - allowed)._citadel_authority_notify_blocked()
        untouched = self - candidates
        actionable = (allowed | untouched).with_context(citadel_business_action=True)
        result = super(PurchaseOrder, actionable).button_confirm() if actionable else True
        allowed.filtered(lambda order: order.state in ("purchase", "done", "to approve"))._citadel_authority_complete()
        return result

    def button_cancel(self):
        result = super().button_cancel()
        self.filtered(lambda order: order.state == "cancel")._citadel_authority_cancel_open()
        return result


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    def _citadel_invalidate_orders(self, orders):
        if self.env.context.get("citadel_business_action"):
            return
        for order in orders:
            request = order.sudo().citadel_authority_request_id
            if request.state in ("pending", "approved"):
                request.with_context(citadel_actor_id=self.env.uid)._citadel_cancel(
                    "invalidated", "Purchase order lines changed."
                )

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._citadel_invalidate_orders(lines.order_id)
        return lines

    def write(self, vals):
        orders = self.order_id
        result = super().write(vals)
        self._citadel_invalidate_orders(orders | self.order_id)
        return result

    def unlink(self):
        orders = self.order_id
        result = super().unlink()
        self._citadel_invalidate_orders(orders)
        return result

