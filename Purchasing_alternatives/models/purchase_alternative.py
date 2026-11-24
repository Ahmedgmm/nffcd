from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
import math
from odoo.tools.float_utils import float_compare, float_is_zero


class PurchaseAlternativeComparison(models.Model):
    _name = "purchase.alternative.comparison"
    _description = "Purchase Alternative Comparison"
    _inherit = ["mail.thread", "mail.activity.mixin", "citadel.authority.mixin"]
    _order = "id desc"
    _check_company_auto = True

    _citadel_guard_fields = {"citadel_committee_employee_ids", "decision_type", "decision_vendor_id"}

    name = fields.Char(required=True, copy=False, default=lambda self: _("New Alternative Comparison"))
    order_id = fields.Many2one(
        "purchase.order",
        string="Original RFQ",
        required=True,
        ondelete="cascade",
        index=True,
        check_company=True,
        copy=False,
    )
    company_id = fields.Many2one(related="order_id.company_id", store=True, readonly=True)
    currency_id = fields.Many2one(related="order_id.currency_id", store=True, readonly=True)
    state = fields.Selection(
        [("draft", "Draft"), ("applied", "Applied"), ("locked", "Locked")],
        default="draft",
        required=True,
        tracking=True,
        copy=False,
    )
    vendor_ids = fields.One2many(
        "purchase.alternative.vendor",
        "comparison_id",
        string="Vendors",
        copy=False,
    )
    line_ids = fields.One2many(
        "purchase.alternative.line",
        "comparison_id",
        string="Offer Lines",
        copy=False,
    )

    citadel_committee_employee_ids = fields.Many2many(
        "hr.employee", "purchase_alternative_committee_employee_rel", "comparison_id", "employee_id",
        string="لجنة البت والمفاضلة", copy=False, tracking=True,
        domain="[('company_id', '=', company_id), ('user_id', '!=', False)]",
    )
    decision_type = fields.Selection(
        [("main", "ترسية على مورد واحد"), ("split", "توزيع الكميات على عدة موردين")],
        string="قرار اللجنة", readonly=True, copy=False, tracking=True,
    )
    decision_vendor_id = fields.Many2one(
        "purchase.alternative.vendor", string="المورد المختار", readonly=True, copy=False,
    )
    decision_amount = fields.Monetary(
        string="قيمة القرار", currency_field="currency_id", compute="_compute_decision_amount",
    )
    is_editable = fields.Boolean(compute="_compute_is_editable")
    split_order_ids = fields.One2many(
        "purchase.order", "alternative_source_comparison_id", string="أوامر الشراء الناتجة",
    )

    _order_unique = models.Constraint(
        "unique(order_id)", "Only one alternative comparison is allowed per RFQ."
    )

    @api.depends("decision_type", "decision_vendor_id", "line_ids.price_subtotal", "line_ids.offered_qty")
    def _compute_decision_amount(self):
        for comparison in self:
            comparison.decision_amount = comparison._citadel_decision_amount()

    @api.depends("state", "order_id.state", "citadel_authority_request_id.state")
    def _compute_is_editable(self):
        for comparison in self:
            comparison.is_editable = (
                comparison.state == "draft"
                and comparison.order_id.state in ("draft", "sent")
                and comparison.sudo().citadel_authority_request_id.state not in ("pending", "approved")
            )

    @api.model
    def create_from_order(self, order, employees=None):
        order.ensure_one()
        vals = {
            "name": _("Alternative Generator - %s") % order.name,
            "order_id": order.id,
        }
        if employees:
            vals["citadel_committee_employee_ids"] = [fields.Command.set(employees.ids)]
        comparison = self.create(vals)
        comparison.sync_from_order()
        return comparison

    # ------------------------------------------------------------------
    # Authority integration (committee approval of the decision)
    # ------------------------------------------------------------------
    def _citadel_authority_document_type(self):
        return "purchase_alternative"

    def _citadel_authority_committee_users(self):
        return self.sudo().citadel_committee_employee_ids.user_id.with_env(self.env)

    def _citadel_authority_committee_required(self):
        return bool(self.citadel_committee_employee_ids)

    def _citadel_authority_currency(self):
        return self.currency_id

    def _citadel_authority_date(self):
        order = self.order_id
        return order.date_order.date() if order.date_order else fields.Date.context_today(self)

    def _citadel_authority_requester(self):
        return self.order_id.user_id or self.create_uid

    def _citadel_decision_lines(self):
        self.ensure_one()
        if self.decision_type == "main":
            return self.decision_vendor_id.line_ids.filtered(lambda line: line._is_positive_qty())
        if self.decision_type == "split":
            return self.line_ids.filtered(lambda line: line._is_positive_qty())
        return self.env["purchase.alternative.line"]

    def _citadel_decision_amount(self):
        self.ensure_one()
        return sum(self._citadel_decision_lines().mapped("price_subtotal"))

    def _citadel_authority_amount(self):
        return self._citadel_decision_amount()

    def _citadel_authority_fingerprint_values(self):
        self.ensure_one()
        return {
            **super()._citadel_authority_fingerprint_values(),
            "order_id": self.order_id.id,
            "decision": self.decision_type,
            "decision_vendor": self.decision_vendor_id.id,
            "committee": sorted(self.citadel_committee_employee_ids.ids),
            "vendors": [
                [vendor.id, vendor.partner_id.id, fields.Datetime.to_string(vendor.date_planned) if vendor.date_planned else False]
                for vendor in self.vendor_ids.sorted("id")
            ],
            "offers": [
                [line.vendor_id.id, line.purchase_order_line_id.id, line.offered_qty, line.price_unit]
                for line in self.line_ids.sorted("id")
            ],
        }

    def _citadel_is_used(self):
        """A comparison only governs the RFQ once alternative vendors were added."""
        self.ensure_one()
        return len(self.vendor_ids) > 1 or bool(self.split_order_ids)

    def _citadel_committee_approved(self, decision_type=None, vendor=None):
        self.ensure_one()
        request = self.sudo().citadel_authority_request_id
        if request.state == "completed":
            approved = True
        else:
            approved = request.state == "approved" and request.fingerprint == self._citadel_authority_fingerprint()
        if not approved:
            return False
        if decision_type and self.decision_type != decision_type:
            return False
        if vendor and self.decision_vendor_id != vendor:
            return False
        return True

    def _citadel_check_committee(self):
        self.ensure_one()
        if not self.citadel_committee_employee_ids:
            raise UserError(_("Select the evaluation committee for %s first.", self.name))
        self._citadel_check_committee_employees(
            self.citadel_committee_employee_ids, self.company_id,
            excluded_users=self._citadel_authority_requester(),
        )

    def _citadel_submit_decision(self, decision_type, vendor=None):
        self.ensure_one()
        self._check_editable()
        self._citadel_check_committee()
        if decision_type == "split":
            self._check_split_allocations()
            if not self.line_ids.filtered(lambda line: line._is_positive_qty()):
                raise UserError(_("Enter at least one positive quantity before submitting the decision."))
            for item in self.vendor_ids:
                if item.line_ids.filtered(lambda line: line._is_positive_qty()) and not item.partner_id:
                    raise UserError(_("Select a vendor for every column with positive quantities."))
        self.with_context(citadel_skip_invalidation=True).write({
            "decision_type": decision_type,
            "decision_vendor_id": vendor.id if vendor else False,
        })
        request = self._citadel_authority_start(require_policy=True)
        self.message_post(body=_(
            "Committee decision submitted for approval (%(request)s): %(decision)s",
            request=request.name,
            decision=dict(self._fields["decision_type"].selection)[decision_type]
            + (" — %s" % vendor.partner_id.display_name if vendor else ""),
        ))
        return request

    def action_submit_main_decision(self, vendor_id):
        self.ensure_one()
        vendor = self._get_vendor_for_action(vendor_id)
        self._citadel_submit_decision("main", vendor)
        return self.get_table_data()

    def action_submit_split_decision(self):
        self.ensure_one()
        self._citadel_submit_decision("split")
        return self.get_table_data()

    def action_reset_committee_decision(self):
        """Withdraw the pending/approved decision so the table can be edited again."""
        for comparison in self:
            if comparison.state != "draft":
                raise UserError(_("An applied comparison cannot be reopened."))
            request = comparison.sudo().citadel_authority_request_id
            if request.state in ("pending", "approved"):
                request.with_context(citadel_actor_id=self.env.uid)._citadel_cancel(
                    "cancelled", _("The buyer withdrew the committee decision.")
                )
            comparison.message_post(body=_("Committee decision withdrawn."))
        return self.get_table_data() if len(self) == 1 else True

    def action_print_committee_minutes(self):
        self.ensure_one()
        return self.env.ref("Purchasing_alternatives.action_report_alternative_committee").report_action(self)

    def action_open_form(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [(False, "form")],
        }

    def _citadel_report_lang(self):
        return "ar_001" if self.env["res.lang"]._lang_get("ar_001") else self.env.lang

    def _citadel_report_day_and_date(self):
        from odoo.addons.citadel_authority.models.purchase_committee import arabic_day_and_date
        self.ensure_one()
        request = self.sudo().citadel_authority_request_id
        value = fields.Date.context_today(self, request.decided_on) if request.decided_on else fields.Date.context_today(self)
        return arabic_day_and_date(value)

    def _citadel_report_votes(self):
        """Map committee user id -> electronic approval datetime."""
        self.ensure_one()
        votes = self.sudo().citadel_authority_request_id.step_ids.vote_ids
        return {vote.principal_id.id: vote.acted_on for vote in votes}

    def sync_from_order(self):
        for comparison in self:
            if not comparison.is_editable:
                continue
            comparison._ensure_original_vendor()
            comparison._ensure_lines_for_current_order()

    def _ensure_original_vendor(self):
        self.ensure_one()
        if not self.order_id.partner_id:
            raise UserError(_("Set the vendor on the original RFQ first."))
        original_vendor = self.vendor_ids.filtered("is_original")[:1]
        vals = {
            "partner_id": self.order_id.partner_id.id,
            "date_planned": self.order_id.date_planned,
            "is_original": True,
            "sequence": 1,
        }
        if original_vendor:
            original_vendor.write(vals)
        else:
            original_vendor = self.env["purchase.alternative.vendor"].create(
                {"comparison_id": self.id, **vals}
            )
        return original_vendor

    def _ensure_lines_for_current_order(self):
        self.ensure_one()
        vendors = self.vendor_ids
        order_lines = self.order_id.order_line.filtered(
            lambda line: not line.display_type
            and line.product_id
            and not getattr(line, "is_downpayment", False)
        )
        for vendor in vendors:
            for order_line in order_lines:
                line = self.line_ids.filtered(
                    lambda item, vendor=vendor, order_line=order_line: item.vendor_id == vendor
                    and item.purchase_order_line_id == order_line
                )[:1]
                if line:
                    continue
                self.env["purchase.alternative.line"].create(
                    {
                        "comparison_id": self.id,
                        "vendor_id": vendor.id,
                        "purchase_order_line_id": order_line.id,
                        "offered_qty": order_line.product_qty if vendor.is_original else 0.0,
                        "price_unit": order_line.price_unit if vendor.is_original else 0.0,
                    }
                )

    def action_add_vendor(self, partner_id=False):
        self.ensure_one()
        self._check_editable()
        partner = self.env["res.partner"].browse(partner_id).exists() if partner_id else self.env["res.partner"]
        vendor = self.env["purchase.alternative.vendor"].create(
            {
                "comparison_id": self.id,
                "partner_id": partner.id if partner else False,
                "sequence": (max(self.vendor_ids.mapped("sequence") or [0]) + 1),
                "date_planned": self.order_id.date_planned,
            }
        )
        self._ensure_lines_for_current_order()
        return vendor.id

    def _check_editable(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("This comparison has already been applied or locked."))
        if self.order_id.state not in ("draft", "sent"):
            raise UserError(_("Alternatives can only change draft RFQs."))
        if self.sudo().citadel_authority_request_id.state in ("pending", "approved"):
            raise UserError(_(
                "The committee decision is under approval or approved. Withdraw it before editing offers."
            ))

    def _check_can_apply(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("This comparison has already been applied or locked."))
        if self.order_id.state not in ("draft", "sent"):
            raise UserError(_("Alternatives can only change draft RFQs."))

    def get_table_data(self):
        self.ensure_one()
        self.sync_from_order()
        product_rows = []
        order_lines = self.order_id.order_line.filtered(
            lambda line: not line.display_type
            and line.product_id
            and not getattr(line, "is_downpayment", False)
        )
        for order_line in order_lines:
            cells = []
            allocated_qty = 0.0
            for vendor in self.vendor_ids.sorted("sequence"):
                line = self.line_ids.filtered(
                    lambda item, vendor=vendor, order_line=order_line: item.vendor_id == vendor
                    and item.purchase_order_line_id == order_line
                )[:1]
                if line:
                    allocated_qty += line.offered_qty
                    cells.append(line._table_cell_values())
            positive_prices = [
                cell["price_unit"]
                for cell in cells
                if cell["offered_qty"] > 0 and cell["price_unit"] > 0
            ]
            lowest_price = min(positive_prices) if positive_prices else 0.0
            for cell in cells:
                cell["is_lowest_price"] = bool(
                    lowest_price
                    and cell["offered_qty"] > 0
                    and cell["price_unit"] == lowest_price
                )
            product_rows.append(
                {
                    "purchase_order_line_id": order_line.id,
                    "product": order_line.product_id.display_name,
                    "requested_qty": order_line.product_qty,
                    "uom": order_line.uom_id.display_name,
                    "allocated_qty": allocated_qty,
                    "remaining_qty": order_line.product_qty - allocated_qty,
                    "allocation_state": self._get_allocation_state(order_line, allocated_qty),
                    "allocation_percent": self._get_allocation_percent(order_line, allocated_qty),
                    "cells": cells,
                }
            )
        request = self.sudo().citadel_authority_request_id
        approved = self._citadel_committee_approved()
        authority = {
            "request": request.name or "",
            "state": request.state or "",
            "approved": approved,
            "can_approve": bool(request.can_approve) if request else False,
            "next": request.next_approval_display or "",
            "approved_by": request.approved_by_display or "",
            "committee": ", ".join(self.citadel_committee_employee_ids.mapped("name")),
            "decision": dict(self._fields["decision_type"].selection).get(self.decision_type, ""),
            "decision_vendor_id": self.decision_vendor_id.id,
            "decision_vendor": self.decision_vendor_id.partner_id.display_name or "",
        }
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state if self.is_editable or self.state != "draft" else "review",
            "authority": authority,
            "order": {
                "id": self.order_id.id,
                "name": self.order_id.name,
                "state": self.order_id.state,
                "partner": self.order_id.partner_id.display_name,
                "currency": self.currency_id.symbol or self.currency_id.name,
            },
            "vendors": [vendor._table_values() for vendor in self.vendor_ids.sorted("sequence")],
            "vendor_options": self._get_vendor_options(),
            "rows": product_rows,
        }

    def _get_allocation_state(self, order_line, allocated_qty):
        requested_qty = order_line.product_qty

        difference = allocated_qty - requested_qty
        if float_compare(allocated_qty, 0.0, precision_digits=self.env["decimal.precision"].precision_get("Product Unit")) <= 0:
            return "empty"
        if float_is_zero(difference, precision_digits=self.env["decimal.precision"].precision_get("Product Unit")):
            return "complete"
        if float_compare(difference, 0.0, precision_digits=self.env["decimal.precision"].precision_get("Product Unit")) > 0:
            return "over"
        return "partial"

    def _get_allocation_percent(self, order_line, allocated_qty):
        requested_qty = order_line.product_qty or 0.0
        if float_is_zero(requested_qty, precision_digits=self.env["decimal.precision"].precision_get("Product Unit")):
            return 0
        return min(round((allocated_qty / requested_qty) * 100), 999)

    def _get_vendor_options(self):
        partners = self.env["res.partner"].search(
            [
                ("supplier_rank", ">", 0),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", self.company_id.id),
            ],
            order="name",
            limit=200,
        )
        if self.order_id.partner_id:
            partners |= self.order_id.partner_id
        return [{"id": partner.id, "name": partner.display_name} for partner in partners.sorted("display_name")]

    def action_update_cell(self, line_id, values):
        self.ensure_one()
        self._check_editable()
        line = self.env["purchase.alternative.line"].browse(line_id).exists()
        if not line or line.comparison_id != self:
            raise UserError(_("Invalid alternative line."))
        allowed = {}
        if "offered_qty" in values:
            allowed["offered_qty"] = float(values["offered_qty"] or 0.0)
        if "price_unit" in values:
            allowed["price_unit"] = float(values["price_unit"] or 0.0)
        if allowed:
            line.write(allowed)
        return self.get_table_data()

    def action_update_vendor(self, vendor_id, values):
        self.ensure_one()
        self._check_editable()
        vendor = self.env["purchase.alternative.vendor"].browse(vendor_id).exists()
        if not vendor or vendor.comparison_id != self:
            raise UserError(_("Invalid vendor column."))
        allowed = {}
        if "partner_id" in values:
            partner_id = int(values["partner_id"] or 0)
            allowed["partner_id"] = partner_id or False
        if "date_planned" in values:
            allowed["date_planned"] = (values["date_planned"] or "").replace("T", " ") or False
        if allowed:
            vendor.write(allowed)
        return self.get_table_data()

    def action_apply_main_vendor(self, vendor_id):
        self.ensure_one()
        self._check_can_apply()
        vendor = self._get_vendor_for_action(vendor_id)
        if not self._citadel_committee_approved("main", vendor):
            raise UserError(_("The committee must approve awarding the order to %s first.", vendor.partner_id.display_name))
        self._apply_vendor_to_order(vendor)
        self.state = "applied"
        self._citadel_authority_complete()
        self.message_post(body=_("Applied vendor %(vendor)s to original RFQ %(rfq)s.", vendor=vendor.partner_id.display_name, rfq=self.order_id.name))
        return self.get_table_data()

    def action_create_po_for_vendor(self, vendor_id):
        self.ensure_one()
        self._check_can_apply()
        vendor = self._get_vendor_for_action(vendor_id)
        if not self._citadel_committee_approved():
            raise UserError(_("The committee must approve a decision before extra RFQs are created."))
        if self.decision_type == "main" and vendor != self.decision_vendor_id:
            raise UserError(_("The committee awarded the order to %s only.", self.decision_vendor_id.partner_id.display_name))
        po = self._create_order_for_vendor(vendor)
        self.message_post(body=_("Created RFQ %(rfq)s for vendor %(vendor)s.", rfq=po.name, vendor=vendor.partner_id.display_name))
        return {
            "type": "ir.actions.act_window",
            "res_model": "purchase.order",
            "res_id": po.id,
            "view_mode": "form",
            "views": [(False, "form")],
        }

    def action_create_split_pos(self):
        self.ensure_one()
        self._check_can_apply()
        if not self._citadel_committee_approved("split"):
            raise UserError(_("The committee must approve the split decision first."))
        self._check_split_allocations()
        original_vendor = self.vendor_ids.filtered("is_original")[:1]
        has_positive_qty = bool(self.line_ids.filtered(lambda line: line._is_positive_qty()))
        created_orders = self.env["purchase.order"]
        for vendor in self.vendor_ids.filtered(lambda item: not item.is_original).sorted("sequence"):
            if not vendor.line_ids.filtered(lambda line: line._is_positive_qty()):
                continue
            if not vendor.partner_id:
                raise UserError(_("Select a vendor for every column with positive quantities."))
            created_orders |= self._create_order_for_vendor(vendor)
        if not has_positive_qty:
            raise UserError(_("Enter at least one positive quantity before creating split RFQs."))
        if original_vendor:
            self._apply_vendor_to_order(original_vendor)
        self.state = "applied"
        self._citadel_authority_complete()
        self.message_post(
            body=_(
                "Created split RFQs by vendor. Updated original RFQ: %(updated)s. New RFQs: %(created)s.",
                updated=original_vendor.partner_id.display_name if original_vendor else _("None"),
                created=", ".join(created_orders.mapped("name")) or _("None"),
            )
        )
        if len(created_orders) == 1:
            return {
                "type": "ir.actions.act_window",
                "res_model": "purchase.order",
                "res_id": created_orders.id,
                "view_mode": "form",
                "views": [(False, "form")],
            }
        domain_ids = (created_orders | self.order_id).ids
        return {
            "type": "ir.actions.act_window",
            "name": _("Split Vendor RFQs"),
            "res_model": "purchase.order",
            "view_mode": "list,form",
            "domain": [("id", "in", domain_ids)],
        }

    def _check_split_allocations(self):
        for order_line in self.order_id.order_line.filtered(
            lambda line: not line.display_type
            and line.product_id
            and not getattr(line, "is_downpayment", False)
        ):
            allocated_qty = sum(
                self.line_ids.filtered(lambda line, order_line=order_line: line.purchase_order_line_id == order_line).mapped(
                    "offered_qty"
                )
            )

            if float_compare(allocated_qty, order_line.product_qty, precision_digits=self.env["decimal.precision"].precision_get("Product Unit")) > 0:
                raise UserError(
                    _(
                        "%(product)s is over allocated. Requested %(requested)s, allocated %(allocated)s.",
                        product=order_line.product_id.display_name,
                        requested=order_line.product_qty,
                        allocated=allocated_qty,
                    )
                )

    def _get_vendor_for_action(self, vendor_id):
        vendor = self.env["purchase.alternative.vendor"].browse(vendor_id).exists()
        if not vendor or vendor.comparison_id != self:
            raise UserError(_("Invalid vendor."))
        if not vendor.partner_id:
            raise UserError(_("Select a vendor before generating a PO."))
        if not vendor.line_ids.filtered(lambda line: line._is_positive_qty()):
            raise UserError(_("Enter at least one positive quantity for this vendor."))
        return vendor

    def _apply_vendor_to_order(self, vendor):
        self.order_id.write(
            {
                "partner_id": vendor.partner_id.id,
                "date_planned": vendor.date_planned or self.order_id.date_planned,
            }
        )
        for line in vendor.line_ids:
            order_line = line.purchase_order_line_id
            order_line.write(
                {
                    "product_qty": line.offered_qty,
                    "price_unit": line.price_unit,
                    "date_planned": vendor.date_planned or order_line.date_planned,
                }
            )

    def _create_order_for_vendor(self, vendor):
        source_order = self.order_id
        vals = self._prepare_split_order_vals(vendor)
        new_order = self.env["purchase.order"].with_context(default_requisition_id=False).create(vals)
        for alt_line in vendor.line_ids.filtered(lambda line: line._is_positive_qty()):
            old_line = alt_line.purchase_order_line_id
            new_line_vals = old_line.copy_data({"order_id": new_order.id})[0]
            for copied_link_field in (
                "invoice_lines",
                "move_ids",
                "move_dest_ids",
                "fuel_delivery_line_ids",
            ):
                new_line_vals.pop(copied_link_field, None)
            if "requisition_agreement_line_id" in old_line._fields:
                # Split lines keep the request source, so they keep its tracking ID.
                new_line_vals["requisition_agreement_line_id"] = old_line.requisition_agreement_line_id.id
            new_line_vals.update(
                {
                    "order_id": new_order.id,
                    "product_qty": alt_line.offered_qty,
                    "price_unit": alt_line.price_unit,
                    "date_planned": vendor.date_planned or old_line.date_planned,
                }
            )
            new_line = self.env["purchase.order.line"].create(new_line_vals)
        if "purchase_group_id" in source_order._fields and source_order.purchase_group_id:
            source_order.purchase_group_id.order_ids |= new_order
        elif "purchase_group_id" in source_order._fields:
            self.env["purchase.order.group"].create({"order_ids": [fields.Command.set((source_order | new_order).ids)]})
        return new_order

    def _prepare_split_order_vals(self, vendor):
        source_order = self.order_id
        vals = {
            "partner_id": vendor.partner_id.id,
            "company_id": source_order.company_id.id,
            "currency_id": source_order.currency_id.id,
            "origin": source_order.origin or source_order.name,
            "user_id": source_order.user_id.id or self.env.user.id,
            "date_order": source_order.date_order,
            "date_planned": vendor.date_planned or source_order.date_planned,
            "is_fuel_po": source_order.is_fuel_po if "is_fuel_po" in source_order._fields else False,
            "alternative_source_comparison_id": self.id,
            "citadel_cost_type": source_order.citadel_cost_type,
        }
        optional_fields = [
            "requisition_agreement_id",
            "picking_type_id",
            "payment_term_id",
            "fiscal_position_id",
            "dest_address_id",
            "incoterm_id",
            "incoterm_location",
            "note",
        ]
        for field_name in optional_fields:
            if field_name in source_order._fields and source_order[field_name]:
                value = source_order[field_name]
                vals[field_name] = value.id if source_order._fields[field_name].type == "many2one" else value
        return {key: value for key, value in vals.items() if value is not False}



class PurchaseAlternativeVendor(models.Model):
    _name = "purchase.alternative.vendor"
    _description = "Purchase Alternative Vendor"
    _order = "sequence, id"
    _check_company_auto = True

    comparison_id = fields.Many2one(
        "purchase.alternative.comparison",
        required=True,
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(related="comparison_id.company_id", store=True, readonly=True)
    currency_id = fields.Many2one(related="comparison_id.currency_id", store=True, readonly=True)
    partner_id = fields.Many2one(
        "res.partner",
        string="Vendor",
        domain="[('supplier_rank', '>', 0), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        check_company=True,
    )
    date_planned = fields.Datetime(string="Delivery Date")
    is_original = fields.Boolean(copy=False)
    sequence = fields.Integer(default=10)
    line_ids = fields.One2many(
        "purchase.alternative.line",
        "vendor_id",
        string="Offer Lines",
        copy=False,
    )
    amount_total = fields.Monetary(compute="_compute_amount_total", currency_field="currency_id")

    @api.depends("line_ids.price_subtotal")
    def _compute_amount_total(self):
        for vendor in self:
            vendor.amount_total = sum(vendor.line_ids.mapped("price_subtotal"))

    def _table_values(self):
        self.ensure_one()
        return {
            "id": self.id,
            "partner_id": self.partner_id.id,
            "partner": self.partner_id.display_name or "",
            "date_planned": fields.Datetime.to_string(self.date_planned) if self.date_planned else "",
            "is_original": self.is_original,
            "amount_total": self.amount_total,
        }


class PurchaseAlternativeLine(models.Model):
    _name = "purchase.alternative.line"
    _description = "Purchase Alternative Line"
    _order = "purchase_order_line_id, vendor_id"
    _check_company_auto = True

    comparison_id = fields.Many2one(
        "purchase.alternative.comparison",
        required=True,
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    vendor_id = fields.Many2one(
        "purchase.alternative.vendor",
        required=True,
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(related="comparison_id.company_id", store=True, readonly=True)
    currency_id = fields.Many2one(related="comparison_id.currency_id", store=True, readonly=True)
    purchase_order_line_id = fields.Many2one(
        "purchase.order.line",
        string="Original RFQ Line",
        required=True,
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    product_id = fields.Many2one(related="purchase_order_line_id.product_id", store=True, readonly=True)
    requested_qty = fields.Float(related="purchase_order_line_id.product_qty", readonly=True)
    product_uom_id = fields.Many2one(related="purchase_order_line_id.uom_id", readonly=True)
    offered_qty = fields.Float(string="Qty", digits="Product Unit", default=0.0)
    price_unit = fields.Float(string="Unit Price", digits="Product Price", default=0.0)
    price_subtotal = fields.Monetary(compute="_compute_price_subtotal", currency_field="currency_id", store=True)

    _vendor_order_line_unique = models.Constraint(
        "unique(vendor_id, purchase_order_line_id)",
        "Each vendor can have only one offer cell per original RFQ line.",
    )

    @api.constrains("offered_qty", "price_unit", "comparison_id", "vendor_id", "purchase_order_line_id")
    def _check_offer(self):
        for line in self:
            if any(not math.isfinite(value) or value < 0 for value in (line.offered_qty, line.price_unit)):
                raise ValidationError(_("Offer quantity and price must be finite and non-negative."))
            if line.vendor_id.comparison_id != line.comparison_id or line.purchase_order_line_id.order_id != line.comparison_id.order_id:
                raise ValidationError(_("Offer vendor and RFQ line must belong to this comparison."))

    @api.depends("offered_qty", "price_unit")
    def _compute_price_subtotal(self):
        for line in self:
            line.price_subtotal = line.offered_qty * line.price_unit

    def _is_positive_qty(self):
        self.ensure_one()

        return float_compare(self.offered_qty, 0.0, precision_digits=self.env["decimal.precision"].precision_get("Product Unit")) > 0

    def _table_cell_values(self):
        self.ensure_one()
        return {
            "id": self.id,
            "vendor_id": self.vendor_id.id,
            "purchase_order_line_id": self.purchase_order_line_id.id,
            "offered_qty": self.offered_qty,
            "price_unit": self.price_unit,
            "subtotal": self.price_subtotal,
        }
