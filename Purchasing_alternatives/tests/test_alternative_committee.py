from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAlternativeCommittee(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        groups = [
            cls.env.ref("citadel_authority.group_citadel_authority_user").id,
            cls.env.ref("purchase.group_purchase_user").id,
            cls.env.ref("stock.group_stock_user").id,
            cls.env.ref("base.group_user").id,
        ]

        def user(login):
            return cls.env["res.users"].with_context(no_reset_password=True).create({
                "name": login, "login": login, "email": "%s@example.com" % login,
                "company_id": cls.company.id, "company_ids": [Command.set(cls.company.ids)],
                "group_ids": [Command.set(groups)],
            })

        cls.buyer = user("alt.buyer")
        cls.members = user("alt.m1") | user("alt.m2") | user("alt.m3")
        cls.employees = cls.env["hr.employee"].create([
            {"name": member.name, "user_id": member.id, "company_id": cls.company.id} for member in cls.members
        ])
        cls.vendor_a = cls.env["res.partner"].create({"name": "Alt Vendor A", "supplier_rank": 1})
        cls.vendor_b = cls.env["res.partner"].create({"name": "Alt Vendor B", "supplier_rank": 1})
        cls.product = cls.env["product.product"].create({"name": "Alt Service", "type": "service"})
        cls.env["citadel.authority.policy"].search([("document_type", "=", "purchase_order")]).active = False

    def _order(self):
        return self.env["purchase.order"].with_user(self.buyer).create({
            "partner_id": self.vendor_a.id,
            "user_id": self.buyer.id,
            "order_line": [Command.create({"product_id": self.product.id, "product_qty": 10.0, "price_unit": 20.0})],
        })

    def _comparison(self, order):
        action = order.with_user(self.buyer).action_open_alternative_generator()
        self.assertEqual(action["res_model"], "purchase.alternative.committee.wizard")
        wizard = self.env["purchase.alternative.committee.wizard"].with_user(self.buyer).create({
            "order_id": order.id, "employee_ids": [Command.set(self.employees.ids)],
        })
        action = wizard.action_create()
        comparison = self.env["purchase.alternative.comparison"].browse(action["params"]["comparison_id"])
        comparison = comparison.with_user(self.buyer)
        vendor_id = comparison.action_add_vendor(self.vendor_b.id)
        vendor = comparison.vendor_ids.browse(vendor_id)
        cell = comparison.line_ids.filtered(lambda line: line.vendor_id == vendor)
        comparison.action_update_cell(cell.id, {"offered_qty": 10.0, "price_unit": 15.0})
        return comparison, vendor

    def test_main_decision_needs_all_members(self):
        order = self._order()
        comparison, vendor = self._comparison(order)
        with self.assertRaisesRegex(UserError, "يجب أن تعتمد اللجنة"):
            comparison.action_apply_main_vendor(vendor.id)
        with self.assertRaisesRegex(UserError, "لم تعتمد لجنة البت والمفاضلة"):
            order.with_user(self.buyer).button_confirm()

        comparison.action_submit_main_decision(vendor.id)
        request = comparison.citadel_authority_request_id
        self.assertEqual(request.state, "pending")
        self.assertEqual(request.amount, 150.0)
        self.assertEqual(request.current_step_ids.eligible_user_ids, self.members)
        with self.assertRaisesRegex(UserError, "قيد الاعتماد"):
            comparison.action_update_cell(comparison.line_ids[0].id, {"price_unit": 1.0})
        with self.assertRaises(UserError):
            comparison.with_user(self.buyer).action_citadel_approve()

        comparison.with_user(self.members[1]).action_citadel_approve()
        comparison.with_user(self.members[2]).action_citadel_approve()
        self.assertEqual(request.state, "pending")
        with self.assertRaisesRegex(UserError, "يجب أن تعتمد اللجنة"):
            comparison.action_apply_main_vendor(vendor.id)
        comparison.with_user(self.members[0]).action_citadel_approve()
        self.assertEqual(request.state, "approved")

        other = comparison.vendor_ids.filtered("is_original")
        with self.assertRaisesRegex(UserError, "يجب أن تعتمد اللجنة"):
            comparison.action_apply_main_vendor(other.id)
        with self.assertRaisesRegex(UserError, "طبّق قرار اللجنة المعتمد"):
            order.with_user(self.buyer).button_confirm()

        html, _type = self.env["ir.actions.report"]._render_qweb_html(
            "Purchasing_alternatives.action_report_alternative_committee", comparison.ids,
        )
        self.assertIn("محضر لجنة البت", html.decode())
        self.assertIn("150.00", html.decode())

        term = self.env["account.payment.term"].create({"name": "Alt 45 days"})
        vendor.payment_term_id = term
        comparison.action_apply_main_vendor(vendor.id)
        self.assertEqual(order.payment_term_id, term)
        self.assertEqual(comparison.state, "applied")
        self.assertEqual(request.state, "completed")
        self.assertEqual(order.partner_id, self.vendor_b)
        self.assertEqual(order.order_line.price_unit, 15.0)
        order.with_user(self.buyer).button_confirm()
        self.assertEqual(order.state, "purchase")

    def test_rejection_and_withdraw(self):
        order = self._order()
        comparison, vendor = self._comparison(order)
        comparison.action_submit_main_decision(vendor.id)
        request = comparison.citadel_authority_request_id
        comparison.with_user(self.members[0]).citadel_authority_request_id._citadel_reject("السعر مرتفع")
        self.assertEqual(request.state, "rejected")
        comparison.action_update_cell(comparison.line_ids.filtered(lambda line: line.vendor_id == vendor).id, {"price_unit": 14.0})
        comparison.action_submit_main_decision(vendor.id)
        comparison.action_reset_committee_decision()
        self.assertEqual(comparison.citadel_authority_request_id.state, "cancelled")
        self.assertTrue(comparison.is_editable)

    def test_split_rfqs_need_approved_comparison(self):
        order = self._order()
        comparison, vendor = self._comparison(order)
        original = comparison.vendor_ids.filtered("is_original")
        comparison.action_update_cell(original.line_ids.id, {"offered_qty": 4.0})
        comparison.action_update_cell(vendor.line_ids.id, {"offered_qty": 6.0})
        comparison.action_submit_split_decision()
        for member in self.members:
            comparison.with_user(member).action_citadel_approve()
        comparison.action_create_split_pos()
        new_order = comparison.split_order_ids
        self.assertEqual(new_order.partner_id, self.vendor_b)
        self.assertEqual(new_order.alternative_source_comparison_id, comparison)
        self.assertEqual(order.order_line.product_qty, 4.0)
        new_order.with_user(self.buyer).button_confirm()
        order.with_user(self.buyer).button_confirm()
        self.assertEqual((order | new_order).mapped("state"), ["purchase", "purchase"])

    def test_unused_comparison_does_not_block(self):
        order = self._order()
        self.env["purchase.alternative.comparison"].create_from_order(order)
        order.with_user(self.buyer).button_confirm()
        self.assertEqual(order.state, "purchase")

    def test_offers_sheet_fields_and_print(self):
        order = self._order()
        chairman = self.employees.sorted("name")[-1]
        wizard = self.env["purchase.alternative.committee.wizard"].with_user(self.buyer).create({
            "order_id": order.id, "employee_ids": [Command.set(self.employees.ids)], "chairman_id": chairman.id,
        })
        comparison = self.env["purchase.alternative.comparison"].browse(
            wizard.action_create()["params"]["comparison_id"]
        ).with_user(self.buyer)
        self.assertEqual(comparison._citadel_ordered_members()[:1], chairman)
        self.assertEqual(comparison.get_table_data()["authority"]["chairman"], chairman.name)
        vendor = comparison.vendor_ids.browse(comparison.action_add_vendor(self.vendor_b.id))
        term = self.env["account.payment.term"].create({"name": "دفع خلال 30 يوم من التوريد"})
        data = comparison.action_update_vendor(vendor.id, {"payment_term_id": str(term.id)})
        self.assertEqual(vendor.payment_term_id, term)
        self.assertIn(term.id, [item["payment_term_id"] for item in data["vendors"]])
        self.assertIn(term.id, [item["id"] for item in data["payment_term_options"]])
        data = comparison.action_update_technical_opinion("مطابق للمواصفات")
        self.assertEqual(data["technical_opinion"], "مطابق للمواصفات")
        with self.assertRaises(Exception):
            comparison.citadel_chairman_employee_id = self.env["hr.employee"].create({"name": "Outsider"})
        html = self.env["ir.actions.report"]._render_qweb_html(
            "Purchasing_alternatives.action_report_alternative_offers_sheet", comparison.ids,
        )[0].decode()
        for text in (order.name.lstrip("P0123456789") or "P", "دفع خلال", "مطابق للمواصفات", "رئيس اللجنة"):
            self.assertIn(text, html)
        self.assertNotIn("مدة سريان العرض", html)
