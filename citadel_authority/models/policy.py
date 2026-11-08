from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval


DOCUMENT_TYPES = [
    ("purchase_order", "أمر شراء"),
    ("sale_order", "أمر بيع"),
    ("vendor_bill", "فاتورة مورد"),
    ("customer_invoice", "فاتورة عميل"),
    ("vendor_refund", "مرتجع مورد"),
    ("customer_credit_note", "إشعار دائن / استرداد"),
    ("journal_entry", "قيد يومية"),
    ("payment", "دفعة"),
]

DOCUMENT_MODELS = {
    "purchase_order": "purchase.order",
    "sale_order": "sale.order",
    "vendor_bill": "account.move",
    "customer_invoice": "account.move",
    "vendor_refund": "account.move",
    "customer_credit_note": "account.move",
    "journal_entry": "account.move",
    "payment": "account.payment",
}


class CitadelAuthorityPolicy(models.Model):
    _name = "citadel.authority.policy"
    _description = "Authority Policy"
    _order = "company_id, document_type, sequence, id"

    name = fields.Char(string="اسم السياسة", required=True, translate=True)
    reference = fields.Char(string="المرجع")
    active = fields.Boolean(string="نشط", default=True)
    sequence = fields.Integer(string="التسلسل", default=10, help="تُطبق أول سياسة مطابقة.")
    company_id = fields.Many2one(
        "res.company", string="الشركة", required=True, default=lambda self: self.env.company, index=True,
    )
    apply_to_child_companies = fields.Boolean(
        string="تطبيق على الشركات التابعة", default=True,
        help="استخدم هذه السياسة كخيار احتياطي للشركات التابعة التي ليس لها سياسة أكثر تحديداً.",
    )
    currency_id = fields.Many2one("res.currency", string="العملة", related="company_id.currency_id")
    document_type = fields.Selection(DOCUMENT_TYPES, string="نوع المستند", required=True, index=True)
    res_model = fields.Char(string="نموذج المستند", compute="_compute_res_model")
    domain = fields.Char(
        string="نطاق التطبيق", default="[]", required=True,
        help="نطاق اختياري يُقيّم على المستند المستهدف.",
    )
    min_amount = fields.Monetary(string="الحد الأدنى", currency_field="currency_id", default=0.0)
    max_amount = fields.Monetary(
        string="الحد الأقصى", currency_field="currency_id", help="الصفر يعني عدم وجود حد أقصى.",
    )
    allow_self_approval = fields.Boolean(string="السماح لمقدم الطلب بالاعتماد")
    allow_same_user_multiple_steps = fields.Boolean(string="السماح للشخص نفسه باعتماد عدة خطوات")
    require_rejection_reason = fields.Boolean(string="إلزام إدخال سبب الرفض", default=True)
    change_threshold_percent = fields.Float(
        string="نسبة التغيير لإعادة الاعتماد", default=0.0,
        help="يبطل الاعتماد عند تغير المبلغ بأكثر من هذه النسبة. الصفر يعني أي تغيير.",
    )
    change_threshold_amount = fields.Monetary(
        string="مبلغ التغيير المسموح", currency_field="currency_id",
        help="التغييرات التي لا تتجاوز هذا المبلغ لا تبطل الاعتماد.",
    )
    sla_hours = fields.Float(string="مهلة الاعتماد بالساعات", help="عدد الساعات المسموح بها قبل تأخر مستوى الاعتماد الحالي.")
    escalation_role_id = fields.Many2one(
        "citadel.authority.role", string="دور التصعيد", check_company=True,
        help="يمكن لأعضاء هذا الدور اتخاذ الإجراء بعد تجاوز المهلة.",
    )
    step_ids = fields.One2many(
        "citadel.authority.policy.step", "policy_id", copy=True, string="خطوات الاعتماد",
    )
    note = fields.Text(string="ملاحظات")

    _amounts_nonnegative = models.Constraint(
        "CHECK(min_amount >= 0 AND max_amount >= 0 AND change_threshold_percent >= 0 AND change_threshold_amount >= 0 AND sla_hours >= 0)",
        "Policy amounts, thresholds, and SLA hours cannot be negative.",
    )

    @api.depends("document_type")
    def _compute_res_model(self):
        for policy in self:
            policy.res_model = DOCUMENT_MODELS.get(policy.document_type)

    @api.constrains("min_amount", "max_amount")
    def _check_amount_range(self):
        for policy in self:
            if policy.max_amount and policy.max_amount < policy.min_amount:
                raise ValidationError(_("Maximum amount must be zero or at least the minimum amount."))

    @api.constrains("domain", "document_type")
    def _check_domain(self):
        for policy in self:
            try:
                domain = safe_eval(policy.domain or "[]")
                self.env[policy.res_model].sudo().search_count(domain, limit=1)
            except Exception as error:
                raise ValidationError(_("Invalid policy domain: %s", error)) from error

    @api.constrains("step_ids", "company_id", "escalation_role_id")
    def _check_steps(self):
        for policy in self:
            approval_steps = policy.step_ids.filtered(lambda step: step.action == "approve")
            if not approval_steps:
                raise ValidationError(_("Policy %s needs at least one approval step.", policy.display_name))
            roles = policy.step_ids.role_id | policy.escalation_role_id
            if any(role.company_id != policy.company_id for role in roles):
                raise ValidationError(_("All policy roles must belong to the policy company."))

    def _citadel_domain(self):
        self.ensure_one()
        return safe_eval(self.domain or "[]")

    @api.model
    def _citadel_company_chain(self, company):
        # Subsidiary users cannot read their sector/foundation parents.
        chain = company.sudo()
        current = chain
        while current.parent_id:
            current = current.parent_id
            chain |= current
        return chain

    @api.model
    def _citadel_find(self, document_type, document, amount):
        company = document.company_id
        chain = self._citadel_company_chain(company)
        policies = self.sudo().search([
            ("active", "=", True),
            ("document_type", "=", document_type),
            ("company_id", "in", chain.ids),
        ])
        depth = {company_id: index for index, company_id in enumerate(chain.ids)}
        policies = policies.sorted(
            lambda policy: (depth.get(policy.company_id.id, 999), policy.sequence, policy.id)
        )
        amount = abs(amount or 0.0)
        for policy in policies:
            if policy.company_id != company and not policy.apply_to_child_companies:
                continue
            company_amount = document._citadel_authority_convert_amount(amount, policy.currency_id)
            if company_amount < policy.min_amount:
                continue
            if policy.max_amount and company_amount > policy.max_amount:
                continue
            if document.sudo().filtered_domain(policy._citadel_domain()):
                return policy, company_amount
        return self.browse(), 0.0


class CitadelAuthorityPolicyStep(models.Model):
    _name = "citadel.authority.policy.step"
    _description = "Authority Policy Step"
    _order = "policy_id, sequence, id"

    policy_id = fields.Many2one(
        "citadel.authority.policy", required=True, ondelete="cascade", index=True,
    )
    company_id = fields.Many2one(related="policy_id.company_id")
    sequence = fields.Integer(string="التسلسل", default=10, required=True)
    role_id = fields.Many2one(
        "citadel.authority.role", string="الدور", required=True, ondelete="restrict", check_company=True,
    )
    action = fields.Selection(
        [("approve", "اعتماد"), ("inform", "للعلم")], string="الإجراء", required=True, default="approve",
    )
    approval_mode = fields.Selection(
        [("any", "أي شخص"), ("all", "الجميع"), ("quorum", "النصاب")], string="أسلوب الاعتماد",
        required=True,
        default="any",
    )
    required_approvals = fields.Integer(string="الاعتمادات المطلوبة", default=1)
    note = fields.Char(string="ملاحظة")

    _required_positive = models.Constraint(
        "CHECK(required_approvals > 0)", "Required approvals must be greater than zero.",
    )

    @api.constrains("approval_mode", "required_approvals", "action")
    def _check_quorum(self):
        for step in self:
            if step.action == "approve" and step.approval_mode != "quorum" and step.required_approvals != 1:
                raise ValidationError(_("Only quorum steps may require more than one approval."))

