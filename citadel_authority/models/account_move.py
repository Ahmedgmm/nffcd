from odoo import api, fields, models


class AccountMove(models.Model):
    _name = "account.move"
    _inherit = ["account.move", "citadel.authority.mixin"]

    _citadel_guard_fields = {
        "company_id", "move_type", "journal_id", "partner_id", "currency_id", "date",
        "invoice_date", "invoice_line_ids", "line_ids", "fiscal_position_id", "invoice_payment_term_id",
    }
    _citadel_amount_fields = {"invoice_line_ids", "line_ids", "currency_id"}

    def _citadel_authority_document_type(self):
        self.ensure_one()
        if self.move_type in ("in_invoice", "in_receipt"):
            return "vendor_bill"
        if self.move_type == "in_refund":
            return "vendor_refund"
        if self.move_type in ("out_invoice", "out_receipt"):
            return "customer_invoice"
        if self.move_type == "out_refund":
            return "customer_credit_note"
        return "journal_entry"

    def _citadel_authority_amount(self):
        self.ensure_one()
        if self.is_invoice(include_receipts=True):
            return abs(self.amount_total)
        return abs(sum(self.line_ids.mapped("debit")))

    def _citadel_authority_currency(self):
        return self.currency_id if self.is_invoice(include_receipts=True) else self.company_currency_id

    def _citadel_authority_date(self):
        return self.invoice_date or self.date or fields.Date.context_today(self)

    def _citadel_authority_fingerprint_values(self):
        self.ensure_one()
        return {
            **super()._citadel_authority_fingerprint_values(),
            "move_type": self.move_type,
            "journal_id": self.journal_id.id,
            "partner_id": self.partner_id.id,
            "currency_id": self.currency_id.id,
            "date": fields.Date.to_string(self.date) if self.date else False,
            "lines": [
                [line.account_id.id, line.partner_id.id, line.debit, line.credit, line.amount_currency]
                for line in self.line_ids.sorted(lambda item: (item.sequence, item.id))
            ],
        }

    def action_post(self):
        candidates = self.filtered(lambda move: move.state == "draft")
        allowed = candidates.filtered(lambda move: move._citadel_authority_gate())
        (candidates - allowed)._citadel_authority_notify_blocked()
        untouched = self - candidates
        actionable = (allowed | untouched).with_context(citadel_business_action=True)
        result = super(AccountMove, actionable).action_post() if actionable else False
        allowed.filtered(lambda move: move.state == "posted")._citadel_authority_complete()
        return result

    def button_cancel(self):
        result = super().button_cancel()
        self.filtered(lambda move: move.state == "cancel")._citadel_authority_cancel_open()
        return result


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def _citadel_invalidate_moves(self, moves):
        if self.env.context.get("citadel_business_action"):
            return
        for move in moves:
            request = move.sudo().citadel_authority_request_id
            if request.state in ("pending", "approved"):
                request.with_context(citadel_actor_id=self.env.uid)._citadel_cancel(
                    "invalidated", "Journal item values changed."
                )

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._citadel_invalidate_moves(lines.move_id)
        return lines

    def write(self, vals):
        moves = self.move_id
        result = super().write(vals)
        self._citadel_invalidate_moves(moves | self.move_id)
        return result

    def unlink(self):
        moves = self.move_id
        result = super().unlink()
        self._citadel_invalidate_moves(moves)
        return result

