from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCitadelAuthorityWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        user_group = cls.env.ref("citadel_authority.group_citadel_authority_user")
        purchase_group = cls.env.ref("purchase.group_purchase_user")
        groups = [user_group.id, purchase_group.id, cls.env.ref("base.group_user").id]
        cls.approver_1 = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Citadel Approver One",
            "login": "citadel.approver.1",
            "email": "approver1@example.com",
            "company_id": cls.company.id,
            "company_ids": [Command.set(cls.company.ids)],
            "group_ids": [Command.set(groups)],
        })
        cls.approver_2 = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Citadel Approver Two",
            "login": "citadel.approver.2",
            "email": "approver2@example.com",
            "company_id": cls.company.id,
            "company_ids": [Command.set(cls.company.ids)],
            "group_ids": [Command.set(groups)],
        })
        cls.delegate = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Citadel Delegate",
            "login": "citadel.delegate",
            "email": "delegate@example.com",
            "company_id": cls.company.id,
            "company_ids": [Command.set(cls.company.ids)],
            "group_ids": [Command.set(groups)],
        })
        cls.role_1 = cls.env["citadel.authority.role"].create({
            "name": "First Approval",
            "code": "FIRST",
            "company_id": cls.company.id,
            "user_ids": [Command.set(cls.approver_1.ids)],
        })
        cls.role_2 = cls.env["citadel.authority.role"].create({
            "name": "Final Approval",
            "code": "FINAL",
            "company_id": cls.company.id,
            "user_ids": [Command.set(cls.approver_2.ids)],
        })
        cls.policy = cls.env["citadel.authority.policy"].create({
            "name": "Purchase Orders",
            "company_id": cls.company.id,
            "document_type": "purchase_order",
            "min_amount": 0,
            "max_amount": 0,
            "step_ids": [
                Command.create({"sequence": 10, "role_id": cls.role_1.id}),
                Command.create({"sequence": 20, "role_id": cls.role_2.id}),
            ],
        })
        cls.vendor = cls.env["res.partner"].create({
            "name": "Citadel Test Vendor", "supplier_rank": 1,
        })
        cls.product = cls.env["product.product"].create({
            "name": "Citadel Test Product", "is_storable": True,
        })

    def _purchase_order(self, amount=100.0):
        return self.env["purchase.order"].create({
            "partner_id": self.vendor.id,
            "company_id": self.company.id,
            "currency_id": self.company.currency_id.id,
            "order_line": [Command.create({
                "product_id": self.product.id,
                "name": self.product.display_name,
                "product_qty": 1.0,
                "uom_id": self.product.uom_id.id,
                "price_unit": amount,
                "date_planned": fields.Datetime.now(),
            })],
        })

    def test_sequential_approval_and_confirmation(self):
        order = self._purchase_order()
        request = order._citadel_authority_start()
        self.assertEqual(request.state, "pending")
        self.assertEqual(request.current_step_ids.role_id, self.role_1)

        request.with_user(self.approver_1).action_approve()
        self.assertEqual(request.state, "pending")
        self.assertEqual(request.current_step_ids.role_id, self.role_2)

        request.with_user(self.approver_2).action_approve()
        self.assertEqual(request.state, "approved")
        order.button_confirm()
        self.assertIn(order.state, ("purchase", "done", "to approve"))
        self.assertEqual(request.state, "completed")
        self.assertEqual(request.log_ids.filtered(lambda log: log.event == "step_approved").mapped("actor_id"),
                         self.approver_1 | self.approver_2)

    def test_waiting_for_me_lists_only_current_approver(self):
        order = self._purchase_order()
        request = order._citadel_authority_start()
        Request = self.env["citadel.authority.request"]
        self.assertIn(request, Request.with_user(self.approver_1).search([("waiting_for_me", "=", True)]))
        self.assertNotIn(request, Request.with_user(self.approver_2).search([("waiting_for_me", "=", True)]))
        self.assertIn(request, Request.with_user(self.approver_2).search([("waiting_for_me", "=", False)]))

        order.button_cancel()
        self.assertEqual(request.state, "cancelled")
        self.assertNotIn(request, Request.with_user(self.approver_1).search([("waiting_for_me", "=", True)]))

    def test_blocked_confirm_notifies_user(self):
        order = self._purchase_order()
        users_model = type(self.env["res.users"])
        with patch.object(users_model, "_bus_send", autospec=True) as bus_send:
            order.button_confirm()
        self.assertEqual(order.state, "draft")
        self.assertEqual(order.citadel_authority_request_id.state, "pending")
        self.assertEqual(bus_send.call_args.args[1], "simple_notification")
        self.assertIn(order.display_name, bus_send.call_args.args[2]["message"])

    def test_only_requester_or_manager_can_withdraw(self):
        order = self._purchase_order()
        request = order._citadel_authority_start()
        self.assertFalse(request.with_user(self.approver_1).can_cancel)
        with self.assertRaises(UserError):
            request.with_user(self.approver_1).action_cancel()
        self.assertTrue(request.can_cancel)

    def test_rejection_reason_follows_policy(self):
        order = self._purchase_order()
        request = order._citadel_authority_start()
        wizard = self.env["citadel.authority.reject.wizard"].with_user(self.approver_1).create({
            "request_id": request.id,
        })
        self.assertTrue(wizard.reason_required)
        with self.assertRaises(UserError):
            wizard.action_reject()
        self.policy.require_rejection_reason = False
        wizard.action_reject()
        self.assertEqual(request.state, "rejected")

    def test_protected_change_invalidates_pending_request(self):
        order = self._purchase_order()
        request = order._citadel_authority_start()
        request.with_user(self.approver_1).action_approve()
        order.order_line.write({"price_unit": 250.0})
        self.assertEqual(request.state, "invalidated")

    def test_delegated_approval_records_principal(self):
        order = self._purchase_order()
        request = order._citadel_authority_start()
        self.env["citadel.authority.delegation"].create({
            "delegator_id": self.approver_1.id,
            "delegate_id": self.delegate.id,
            "scope": "purchase_order",
            "company_id": self.company.id,
            "date_start": fields.Date.today(),
            "date_end": fields.Date.today(),
        })
        request.with_user(self.delegate).action_approve()
        vote = request.step_ids.filtered(lambda step: step.role_id == self.role_1).vote_ids
        self.assertEqual(vote.principal_id, self.approver_1)
        self.assertEqual(vote.acted_by_id, self.delegate)

    def test_parent_policy_applies_to_child_company(self):
        child = self.env["res.company"].create({
            "name": "Citadel Child Company", "parent_id": self.company.id,
        })
        (self.approver_1 | self.approver_2).write({"company_ids": [Command.link(child.id)]})
        vendor = self.vendor.with_company(child)
        order = self.env["purchase.order"].with_company(child).create({
            "partner_id": vendor.id,
            "company_id": child.id,
            "currency_id": child.currency_id.id,
            "order_line": [Command.create({
                "product_id": self.product.id,
                "name": self.product.display_name,
                "product_qty": 1.0,
                "uom_id": self.product.uom_id.id,
                "price_unit": 100.0,
                "date_planned": fields.Datetime.now(),
            })],
        })
        request = order._citadel_authority_start()
        self.assertEqual(request.policy_id, self.policy)
        self.assertEqual(request.company_id, child)

    def test_journal_entry_adapter_posts_after_approval(self):
        expense = self.env["account.account"].search([
            ("company_ids", "in", self.company.id),
            ("account_type", "=", "expense"),
        ], limit=1)
        counterpart = self.env["account.account"].search([
            ("company_ids", "in", self.company.id),
            ("account_type", "in", ("liability_current", "asset_current")),
        ], limit=1)
        journal = self.env["account.journal"].search([
            ("company_id", "=", self.company.id), ("type", "=", "general"),
        ], limit=1)
        self.assertTrue(expense and counterpart and journal)
        self.env["citadel.authority.policy"].create({
            "name": "Manual Journal Entries",
            "company_id": self.company.id,
            "document_type": "journal_entry",
            "step_ids": [Command.create({"sequence": 10, "role_id": self.role_1.id})],
        })
        move = self.env["account.move"].create({
            "journal_id": journal.id,
            "date": fields.Date.today(),
            "line_ids": [
                Command.create({"name": "Citadel debit", "account_id": expense.id, "debit": 100.0}),
                Command.create({"name": "Citadel credit", "account_id": counterpart.id, "credit": 100.0}),
            ],
        })
        request = move._citadel_authority_start()
        request.with_user(self.approver_1).action_approve()
        move.action_post()
        self.assertEqual(move.state, "posted")
        self.assertEqual(request.state, "completed")

    def test_credit_notes_and_vendor_refunds_use_separate_policies(self):
        self.env["citadel.authority.policy"].create({
            "name": "Customer Credit Notes",
            "company_id": self.company.id,
            "document_type": "customer_credit_note",
            "step_ids": [Command.create({"sequence": 10, "role_id": self.role_1.id})],
        })
        self.env["citadel.authority.policy"].create({
            "name": "Vendor Refunds",
            "company_id": self.company.id,
            "document_type": "vendor_refund",
            "step_ids": [Command.create({"sequence": 10, "role_id": self.role_2.id})],
        })
        sale_journal = self.env["account.journal"].search([
            ("company_id", "=", self.company.id), ("type", "=", "sale"),
        ], limit=1)
        purchase_journal = self.env["account.journal"].search([
            ("company_id", "=", self.company.id), ("type", "=", "purchase"),
        ], limit=1)
        self.assertTrue(sale_journal and purchase_journal)
        credit_note = self.env["account.move"].create({
            "move_type": "out_refund",
            "journal_id": sale_journal.id,
            "partner_id": self.vendor.id,
        })
        vendor_refund = self.env["account.move"].create({
            "move_type": "in_refund",
            "journal_id": purchase_journal.id,
            "partner_id": self.vendor.id,
        })
        credit_request = credit_note._citadel_authority_start()
        refund_request = vendor_refund._citadel_authority_start()
        self.assertEqual(credit_request.document_type, "customer_credit_note")
        self.assertEqual(credit_request.current_step_ids.role_id, self.role_1)
        self.assertEqual(refund_request.document_type, "vendor_refund")
        self.assertEqual(refund_request.current_step_ids.role_id, self.role_2)

    def test_sales_order_adapter_confirms_after_approval(self):
        self.env["citadel.authority.policy"].create({
            "name": "Sales Orders",
            "company_id": self.company.id,
            "document_type": "sale_order",
            "step_ids": [Command.create({"sequence": 10, "role_id": self.role_1.id})],
        })
        customer = self.env["res.partner"].create({"name": "Citadel Test Customer", "customer_rank": 1})
        order = self.env["sale.order"].create({
            "partner_id": customer.id,
            "company_id": self.company.id,
            "order_line": [Command.create({
                "product_id": self.product.id,
                "name": self.product.display_name,
                "product_uom_qty": 1.0,
                "product_uom_id": self.product.uom_id.id,
                "price_unit": 150.0,
            })],
        })
        request = order._citadel_authority_start()
        request.with_user(self.approver_1).action_approve()
        order.action_confirm()
        self.assertEqual(order.state, "sale")
        self.assertEqual(request.state, "completed")

