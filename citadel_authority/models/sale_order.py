from odoo import api, fields, models


class SaleOrder(models.Model):
    _name = "sale.order"
    _inherit = ["sale.order", "citadel.authority.mixin"]

    _citadel_guard_fields = {
        "company_id", "partner_id", "partner_invoice_id", "partner_shipping_id", "currency_id",
        "date_order", "validity_date", "order_line", "payment_term_id", "fiscal_position_id", "user_id",
    }
    _citadel_amount_fields = {"order_line", "currency_id"}

    def _citadel_authority_document_type(self):
        return "sale_order"

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
            "partner_invoice_id": self.partner_invoice_id.id,
            "partner_shipping_id": self.partner_shipping_id.id,
            "currency_id": self.currency_id.id,
            "date_order": fields.Datetime.to_string(self.date_order) if self.date_order else False,
            "lines": [
                [line.product_id.id, line.product_uom_qty, line.product_uom_id.id, line.price_unit,
                 line.discount, sorted(line.tax_ids.ids)]
                for line in self.order_line.sorted(lambda item: (item.sequence, item.id))
            ],
        }

    def action_confirm(self):
        candidates = self.filtered(lambda order: order.state in ("draft", "sent"))
        allowed = candidates.filtered(lambda order: order._citadel_authority_gate())
        (candidates - allowed)._citadel_authority_notify_blocked()
        untouched = self - candidates
        actionable = (allowed | untouched).with_context(citadel_business_action=True)
        result = super(SaleOrder, actionable).action_confirm() if actionable else True
        allowed.filtered(lambda order: order.state in ("sale", "done"))._citadel_authority_complete()
        return result

    def action_cancel(self):
        result = super().action_cancel()
        self.filtered(lambda order: order.state == "cancel")._citadel_authority_cancel_open()
        return result


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    def _citadel_invalidate_orders(self, orders):
        if self.env.context.get("citadel_business_action"):
            return
        for order in orders:
            request = order.sudo().citadel_authority_request_id
            if request.state in ("pending", "approved"):
                request.with_context(citadel_actor_id=self.env.uid)._citadel_cancel(
                    "invalidated", "Sales order lines changed."
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
