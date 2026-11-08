from odoo import fields, models


class AccountPayment(models.Model):
    _name = "account.payment"
    _inherit = ["account.payment", "citadel.authority.mixin"]

    _citadel_guard_fields = {
        "company_id", "partner_id", "currency_id", "date", "amount", "payment_type",
        "partner_type", "journal_id", "payment_method_line_id", "partner_bank_id",
    }
    _citadel_amount_fields = {"amount", "currency_id"}

    def _citadel_authority_document_type(self):
        return "payment"

    def _citadel_authority_amount(self):
        self.ensure_one()
        return abs(self.amount)

    def _citadel_authority_currency(self):
        return self.currency_id

    def _citadel_authority_date(self):
        return self.date or fields.Date.context_today(self)

    def _citadel_authority_fingerprint_values(self):
        self.ensure_one()
        return {
            **super()._citadel_authority_fingerprint_values(),
            "partner_id": self.partner_id.id,
            "currency_id": self.currency_id.id,
            "date": fields.Date.to_string(self.date) if self.date else False,
            "payment_type": self.payment_type,
            "partner_type": self.partner_type,
            "journal_id": self.journal_id.id,
            "payment_method_line_id": self.payment_method_line_id.id,
            "partner_bank_id": self.partner_bank_id.id,
        }

    def action_post(self):
        candidates = self.filtered(lambda payment: payment.state in (False, "draft", "paid"))
        allowed = candidates.filtered(lambda payment: payment._citadel_authority_gate())
        (candidates - allowed)._citadel_authority_notify_blocked()
        untouched = self - candidates
        actionable = (allowed | untouched).with_context(citadel_business_action=True)
        result = super(AccountPayment, actionable).action_post() if actionable else True
        allowed.filtered(lambda payment: payment.state not in (False, "draft"))._citadel_authority_complete()
        return result

    def action_cancel(self):
        result = super().action_cancel()
        self._citadel_authority_cancel_open()
        return result

