
from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCitadelPurchaseWorkflow(TransactionCase):
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

        cls.buyer = user("pw.buyer")
        cls.wh_admin = user("pw.wh.admin")
        cls.members = user("pw.m1") | user("pw.m2") | user("pw.m3")
        cls.employees = cls.env["hr.employee"].create([
            {"name": member.name, "user_id": member.id, "company_id": cls.company.id, "job_title": "مهندس"}
            for member in cls.members
        ])
        cls.plain_employees = cls.env["hr.employee"].create([
            {"name": "Paper Member %s" % index, "company_id": cls.company.id} for index in range(3)
        ])
        cls.warehouse = cls.env["stock.warehouse"].search([("company_id", "=", cls.company.id)], limit=1)
        cls.warehouse.citadel_receipt_manager_id = cls.wh_admin
        cls.vendor = cls.env["res.partner"].create({"name": "PW Vendor", "supplier_rank": 1})
        cls.product = cls.env["product.product"].create({"name": "PW Product", "is_storable": True})
        # No PO policy: keep the purchase-order level out of these committee tests.
        cls.env["citadel.authority.policy"].search([("document_type", "=", "purchase_order")]).active = False

    def _order(self, price=50.0):
        return self.env["purchase.order"].with_user(self.buyer).create({
            "partner_id": self.vendor.id,
            "company_id": self.company.id,
            "user_id": self.buyer.id,
            "picking_type_id": self.warehouse.in_type_id.id,
            "order_line": [Command.create({
                "product_id": self.product.id, "product_qty": 4.0, "price_unit": price,
            })],
        })

    def _set_committee(self, order, employees=None):
        wizard = self.env["citadel.purchase.receipt.committee.wizard"].with_user(self.buyer).create({
            "order_id": order.id, "employee_ids": [Command.set((employees or self.employees).ids)],
            "next_step": "confirm",
        })
        return wizard.action_apply()

    def test_pricing_committee_requires_signed_scan_and_prices(self):
        order = self._order(price=0.0)
        action = order.with_user(self.buyer).action_view_pricing_committees()
        self.assertEqual((action["view_mode"], action["target"]), ("form", "new"))
        with self.assertRaisesRegex(UserError, "at least 3"):
            self.env["citadel.purchase.pricing.committee"].create({
                "order_id": order.id, "employee_ids": [Command.set(self.plain_employees[:2].ids)],
            })
        committee = self.env["citadel.purchase.pricing.committee"].with_user(self.buyer).create({
            "order_id": order.id, "employee_ids": [Command.set(self.plain_employees.ids)],
            "chairman_id": self.plain_employees[1].id,
        })
        self.assertEqual(committee._citadel_ordered_members()[0], self.plain_employees[1])
        self.assertEqual(order.with_user(self.buyer).action_view_pricing_committees()["view_mode"], "list,form")
        pdf, _type = self.env["ir.actions.report"]._render_qweb_html(
            "citadel_authority.action_report_pricing_committee", committee.ids,
        )
        self.assertIn("محضر لجنة تسعير", pdf.decode())
        with self.assertRaisesRegex(UserError, "signed"):
            order.with_user(self.buyer).button_confirm()
        attachment = self.env["ir.attachment"].with_user(self.buyer).create({
            "name": "signed.pdf", "raw": b"%PDF-1.4 signed",
            "res_model": committee._name, "res_id": committee.id,
        })
        committee.signed_attachment_ids = [Command.set(attachment.ids)]
        with self.assertRaisesRegex(UserError, "committee prices"):
            order.with_user(self.buyer).button_confirm()
        order.order_line.price_unit = 75.0
        action = order.with_user(self.buyer).button_confirm()
        self.assertEqual(action["res_model"], "citadel.purchase.receipt.committee.wizard")

    def test_receipt_committee_parallel_approval_and_manager_validation(self):
        order = self._order()
        action = order.with_user(self.buyer).button_confirm()
        self.assertEqual(action["res_model"], "citadel.purchase.receipt.committee.wizard")
        with self.assertRaisesRegex(UserError, "at least 3"):
            self._set_committee(order, self.employees[:2])
        self._set_committee(order)
        self.assertEqual(order.state, "purchase")
        picking = order.picking_ids
        self.assertEqual(picking.citadel_committee_employee_ids, self.employees)
        request = picking.citadel_authority_request_id
        self.assertEqual(request.state, "pending")
        self.assertEqual(request.requested_by_id, self.buyer)
        self.assertEqual(len(request.current_step_ids), 1)
        self.assertEqual(request.current_step_ids.eligible_user_ids, self.members)
        self.assertFalse(picking.with_user(self.wh_admin).citadel_receipt_can_validate)

        # Not validated before all members approve (parallel: any order).
        picking.with_user(self.wh_admin).button_validate()
        self.assertNotEqual(picking.state, "done")
        for member in self.members[::-1][:2]:
            picking.with_user(member).action_citadel_approve()
        self.assertEqual(request.state, "pending")
        picking.with_user(self.members[0]).action_citadel_approve()
        self.assertEqual(request.state, "approved")

        picking.invalidate_recordset()
        self.assertTrue(picking.with_user(self.wh_admin).citadel_receipt_can_validate)
        self.assertFalse(picking.with_user(self.members[0]).citadel_receipt_can_validate)
        with self.assertRaisesRegex(UserError, "Only the warehouse receipt manager"):
            picking.with_user(self.members[0]).button_validate()
        picking.with_user(self.wh_admin).button_validate()
        self.assertEqual(picking.state, "done")
        self.assertEqual(request.state, "completed")
        html, _type = self.env["ir.actions.report"]._render_qweb_html(
            "citadel_authority.action_report_receipt_committee", picking.ids,
        )
        self.assertIn("محضر فحص واستلام", html.decode())

    def test_quantity_change_needs_new_committee_approval_and_backorder(self):
        order = self._order()
        self._set_committee(order)
        picking = order.picking_ids
        for member in self.members:
            picking.with_user(member).action_citadel_approve()
        first_request = picking.citadel_authority_request_id
        self.assertEqual(first_request.state, "approved")
        picking.move_ids.quantity = 3.0
        picking.invalidate_recordset()
        self.assertTrue(picking.citadel_authority_requires_approval)
        picking.with_user(self.wh_admin).button_validate()
        self.assertNotEqual(picking.state, "done")
        second_request = picking.citadel_authority_request_id
        self.assertNotEqual(second_request, first_request)
        self.assertEqual(first_request.state, "invalidated")
        for member in self.members:
            picking.with_user(member).action_citadel_approve()
        result = picking.with_user(self.wh_admin).button_validate()
        if isinstance(result, dict) and result.get("res_model") == "stock.backorder.confirmation":
            self.env["stock.backorder.confirmation"].with_user(self.wh_admin).with_context(
                **result["context"]
            ).create({}).process()
        self.assertEqual(picking.state, "done")
        backorder = order.picking_ids - picking
        self.assertEqual(len(backorder), 1)
        self.assertEqual(backorder.citadel_committee_employee_ids, self.employees)
        self.assertEqual(backorder.citadel_authority_request_id.state, "pending")

    def test_requester_and_manager_cannot_be_members(self):
        order = self._order()
        buyer_employee = self.env["hr.employee"].create({
            "name": "Buyer Employee", "user_id": self.buyer.id, "company_id": self.company.id,
        })
        with self.assertRaisesRegex(UserError, "cannot be a committee member"):
            self._set_committee(order, self.employees[:2] | buyer_employee)

    def test_manual_receipt_without_committee_is_unchanged(self):
        order = self._order()
        self._set_committee(order)  # creates the company's committee policy
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse.in_type_id.id,
            "partner_id": self.vendor.id,
            "move_ids": [Command.create({
                "product_id": self.product.id, "product_uom_qty": 1.0,
                "location_id": self.warehouse.in_type_id.default_location_src_id.id,
                "location_dest_id": self.warehouse.lot_stock_id.id,
            })],
        })
        picking.action_confirm()
        picking.move_ids.quantity = 1.0
        self.assertFalse(picking.citadel_authority_requires_approval)
        picking.button_validate()
        self.assertEqual(picking.state, "done")

    def test_purchase_request_printout(self):
        department = self.env["hr.department"].create({"name": "إدارة المخازن", "company_id": self.company.id})
        requester = self.env["hr.employee"].create({
            "name": "سامح عادل", "user_id": self.buyer.id, "company_id": self.company.id,
            "department_id": department.id,
        })
        order = self._order()
        self.assertEqual(order.citadel_request_department_id, department)
        order.write({
            "citadel_purchase_purpose": "توفير آلات حاسبة",
            "citadel_purchase_method": "practice",
        })
        self.assertNotIn("citadel_estimated_amount", order._fields)
        self.company.write({"citadel_letterhead_phone": "3364739", "citadel_letterhead_fax": "3373118"})
        html, _type = self.env["ir.actions.report"]._render_qweb_html(
            "citadel_authority.action_report_purchase_request", order.ids,
        )
        html = html.decode()
        for text in ("طلب شراء", "إدارة المخازن", requester.name, "القسم الطالب للشراء", "توفير آلات حاسبة", "( ✓ )", "ممارسة",
                     "رصيد المخزن", "لا يوجد", "لجنة إحضار عروض الأسعار", "لجنة البت والترسية",
                     "3364739", "3373118"):
            self.assertIn(text, html)
