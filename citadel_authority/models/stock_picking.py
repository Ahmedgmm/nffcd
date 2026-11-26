from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


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
    _citadel_auto_execute = True

    citadel_committee_employee_ids = fields.Many2many(
        "hr.employee", "citadel_picking_committee_employee_rel", "picking_id", "employee_id",
        string="لجنة الفحص والاستلام", copy=True,
        domain="[('company_id', '=', company_id)]",
    )
    citadel_receipt_manager_id = fields.Many2one(
        "res.users", string="مسؤول المخزن", compute="_compute_citadel_receipt_manager",
    )
    citadel_receipt_can_validate = fields.Boolean(compute="_compute_citadel_receipt_can_validate")
    citadel_receipt_can_request = fields.Boolean(compute="_compute_citadel_receipt_can_validate")

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
                picking.citadel_receipt_can_request = False
                continue
            is_manager = self.env.su or picking.citadel_receipt_manager_id == self.env.user
            request = picking.sudo().citadel_authority_request_id
            open_state = picking.state not in ("done", "cancel")
            # Validate only shows as a fallback when an approved receipt could not be posted automatically.
            picking.citadel_receipt_can_validate = is_manager and not picking.citadel_authority_requires_approval
            picking.citadel_receipt_can_request = bool(
                is_manager and open_state and picking.citadel_authority_requires_approval and (
                    request.state != "pending" or request.fingerprint != picking._citadel_authority_fingerprint()
                )
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
        """Committee receipts are initiated by the warehouse manager; others by the purchase requester."""
        self.ensure_one()
        if self._citadel_authority_committee_required() and self.citadel_receipt_manager_id:
            return self.citadel_receipt_manager_id
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
                    "لم يُحدد مسؤول المخزن (اعتماد الاستلام) للمخزن %s، لذلك لا يمكن اعتماد الاستلام."
                    "\n\nالحل: المخزون ← الإعدادات ← المخازن: افتح المخزن وحدد «مسؤول المخزن (اعتماد الاستلام)»، ثم يعتمد هو الاستلام.",
                    picking.picking_type_id.warehouse_id.display_name,
                ))
            if manager != self.env.user:
                raise UserError(_(
                    "لا يمكنك اعتماد (Validate) الاستلام %(picking)s؛ هذا الإجراء لمسؤول المخزن %(manager)s فقط."
                    "\n\nالحل: يسجل %(manager)s الدخول ويعتمد الاستلام بعد اكتمال اعتماد لجنة الفحص والاستلام.",
                    manager=manager.display_name, picking=picking.display_name,
                ))

    def _citadel_check_receipt_ready(self):
        """Everything the automatic posting needs, checked before the committee is asked."""
        for picking in self:
            if picking.state in ("done", "cancel"):
                raise UserError(_(
                    "الاستلام %s مُرحّل أو ملغى بالفعل."
                    "\n\nالحل: لا يلزم إجراء على هذا الاستلام.", picking.display_name,
                ))
            if picking.state == "draft":
                raise UserError(_(
                    "الاستلام %s ما زال مسودة."
                    "\n\nالحل: اضغط «تحديد كجاهز» (Mark as To Do) أولاً، ثم أدخل الكميات المستلمة.", picking.display_name,
                ))
            moves = picking.move_ids.filtered(lambda move: move.state not in ("done", "cancel"))
            if not any(move.quantity > 0 for move in moves):
                raise UserError(_(
                    "لم تُدخل أي كمية مستلمة في %s."
                    "\n\nالحل: اكتب الكمية المستلمة فعلاً في عمود «الكمية» لكل صنف، ثم اضغط «طلب اعتماد الاستلام».",
                    picking.display_name,
                ))
            missing_lots = picking.move_line_ids.filtered(
                lambda line: line.quantity > 0 and line.product_id.tracking in ("lot", "serial")
                and not line.lot_id and not line.lot_name
            )
            if missing_lots:
                raise UserError(_(
                    "لم تُدخل أرقام التشغيلات/السيريال للأصناف: %s."
                    "\n\nالحل: افتح تفاصيل الصنف (أيقونة القائمة بجوار الكمية) وأدخل رقم التشغيلة أو السيريال، ثم اضغط «طلب اعتماد الاستلام».",
                    ", ".join(missing_lots.product_id.mapped("display_name")),
                ))

    def action_citadel_request_receipt_approval(self):
        """Warehouse manager: send the entered quantities to the receipt committee."""
        for picking in self:
            if not picking._citadel_authority_committee_required():
                picking._citadel_authority_start(require_policy=True)
                continue
            picking._citadel_check_receipt_manager()
            picking._citadel_check_receipt_ready()
            request = picking._citadel_authority_start(require_policy=True)
            picking.message_post(body=_(
                "أرسل مسؤول المخزن %(manager)s الكميات المستلمة لاعتماد لجنة الفحص والاستلام (%(request)s). "
                "يُرحّل الاستلام تلقائياً بعد اعتماد آخر عضو.",
                manager=self.env.user.display_name, request=request.name,
            ))
        return True

    def action_citadel_request_approval(self):
        committee = self.filtered(lambda picking: picking._citadel_authority_committee_required())
        if committee:
            committee.action_citadel_request_receipt_approval()
        others = self - committee
        return super(StockPicking, others).action_citadel_request_approval() if others else True

    def _citadel_authority_on_final_approval(self):
        """Post the receipt automatically, with the warehouse manager's rights, after the last approval."""
        receipts = self.filtered(
            lambda picking: picking._citadel_authority_committee_required() and picking.state not in ("done", "cancel")
        )
        for picking in receipts:
            picking._citadel_receipt_execute()
        others = self - receipts
        if others:
            return super(StockPicking, others)._citadel_authority_on_final_approval()
        return True

    def _citadel_receipt_execute(self):
        """Validate an approved committee receipt as its warehouse manager.

        The approver never needs stock rights: the posting runs with the manager's
        access rights, only for the exact quantities the committee approved. A failure
        keeps the approval and hands the manager a clear activity to finish it.
        """
        self.ensure_one()
        picking = self.sudo()
        manager = picking.citadel_receipt_manager_id
        request = picking.citadel_authority_request_id
        if not manager:
            return picking._citadel_receipt_execute_failed(_(
                "لم يُحدد مسؤول المخزن للمخزن %s."
                "\n\nالحل: المخزون ← الإعدادات ← المخازن: حدد «مسؤول المخزن (اعتماد الاستلام)»، ثم يضغط «تأكيد» (Validate) على الاستلام.",
                picking.picking_type_id.warehouse_id.display_name,
            ))
        if request.state != "approved" or request.fingerprint != picking._citadel_authority_fingerprint():
            return picking._citadel_receipt_execute_failed(_(
                "تغيّرت الكميات أو بيانات الاستلام بعد إرساله للجنة، فلم يُرحّل."
                "\n\nالحل: راجع الكميات ثم اضغط «طلب اعتماد الاستلام» من جديد لتعتمدها اللجنة."
            ))
        as_manager = self.with_user(manager).with_company(picking.company_id).with_context(
            citadel_business_action=True, skip_backorder=True, skip_sms=True,
        )
        try:
            with self.env.cr.savepoint():
                as_manager.button_validate()
                if as_manager.state != "done":
                    raise UserError(_("يحتاج الاستلام إلى خطوة إضافية في شاشة التأكيد."))
        except (UserError, ValidationError, AccessError) as error:
            return picking._citadel_receipt_execute_failed(_(
                "اعتمدت اللجنة الاستلام لكن تعذّر ترحيله تلقائياً: %s"
                "\n\nالحل: يفتح مسؤول المخزن الاستلام ويعالج السبب أعلاه، ثم يضغط «تأكيد» (Validate) لترحيله بالكميات المعتمدة.",
                error.args[0] if error.args else error,
            ))
        picking._citadel_authority_complete()
        backorders = picking.backorder_ids
        picking.message_post(body=_(
            "تم ترحيل الاستلام تلقائياً بعد اعتماد لجنة الفحص والاستلام، بصلاحية مسؤول المخزن %(manager)s.%(backorder)s",
            manager=manager.display_name,
            backorder=(_(" الكمية المتبقية في الاستلام الجديد %s، ويبدأ اعتماده عندما يُدخل مسؤول المخزن الكميات ويضغط «طلب اعتماد الاستلام».")
                       % ", ".join(backorders.mapped("name"))) if backorders else "",
        ))
        return True

    def _citadel_receipt_execute_failed(self, reason):
        self.ensure_one()
        picking = self.sudo()
        picking.message_post(body=reason)
        manager = picking.citadel_receipt_manager_id
        if manager:
            picking.activity_schedule(
                "mail.mail_activity_data_todo", user_id=manager.id,
                summary=_("أكمل ترحيل الاستلام %s", picking.name), note=reason,
            )
        return False

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
        for picking in governed.filtered(lambda item: item._citadel_authority_committee_required()):
            if picking.citadel_authority_requires_approval:
                request = picking.sudo().citadel_authority_request_id
                if request.state == "pending" and request.fingerprint == picking._citadel_authority_fingerprint():
                    raise UserError(_(
                        "الاستلام %(picking)s بانتظار اعتماد لجنة الفحص والاستلام (%(next)s)."
                        "\n\nالحل: لا حاجة للضغط على «تأكيد»؛ يُرحّل الاستلام تلقائياً بعد اعتماد آخر عضو.",
                        picking=picking.display_name, next=request.next_approval_display or "-",
                    ))
                raise UserError(_(
                    "لا يُرحّل الاستلام %s يدوياً لأنه خاضع للجنة الفحص والاستلام."
                    "\n\nالحل: أدخل الكميات المستلمة ثم اضغط «طلب اعتماد الاستلام»؛ يُرحّل تلقائياً بعد اعتماد آخر عضو.",
                    picking.display_name,
                ))
        allowed = governed.filtered(lambda picking: picking._citadel_authority_gate())
        (governed - allowed)._citadel_authority_notify_blocked()
        actionable = (self - governed) | allowed
        if not actionable:
            return True
        result = super(StockPicking, actionable.with_context(citadel_business_action=True)).button_validate()
        allowed.filtered(lambda picking: picking.state == "done")._citadel_authority_complete()
        return result

    def _create_backorder(self, backorder_moves=None, from_manual_backorder=False):
        # Backorders keep the committee (copied) and wait for the manager to enter quantities and request approval.
        return super()._create_backorder(backorder_moves=backorder_moves, from_manual_backorder=from_manual_backorder)

    def action_cancel(self):
        result = super().action_cancel()
        self.filtered(lambda picking: picking.state == "cancel")._citadel_authority_cancel_open()
        return result
