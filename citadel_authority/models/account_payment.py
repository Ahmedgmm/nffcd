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
        blocked = candidates - allowed
        # «تسجيل الدفع» creates the payment already marked paid; keep blocked ones in draft until approved.
        blocked.filtered(lambda payment: payment.state == "paid").with_context(citadel_business_action=True).write(
            {"state": "draft"}
        )
        blocked._citadel_authority_notify_blocked()
        untouched = self - candidates
        actionable = (allowed | untouched).with_context(citadel_business_action=True)
        result = super(AccountPayment, actionable).action_post() if actionable else True
        posted = allowed.filtered(lambda payment: payment.state not in (False, "draft"))
        posted._citadel_reconcile_matched_invoices()
        posted._citadel_authority_complete()
        return result

    def _citadel_reconcile_matched_invoices(self):
        """Settle the bills/invoices a payment was registered for once it is posted after approval.

        The register-payment wizard reconciles only payments it could post itself; an approved
        payment is posted later, so its open payable/receivable lines are matched here.
        """
        account_types = self._get_valid_payment_account_types()
        for payment in self.filtered(lambda pay: pay.move_id.state == "posted" and pay.invoice_ids):
            lines = payment.move_id.line_ids | payment.invoice_ids.filtered(
                lambda move: move.state == "posted"
            ).line_ids
            open_lines = lines.filtered(
                lambda line: line.account_id.account_type in account_types and not line.reconciled
            )
            for account in payment.move_id.line_ids.filtered(lambda line: line in open_lines).account_id:
                to_match = open_lines.filtered(lambda line: line.account_id == account)
                if to_match.filtered("debit") and to_match.filtered("credit"):
                    to_match.reconcile()

    def action_cancel(self):
        result = super().action_cancel()
        self._citadel_authority_cancel_open()
        return result

