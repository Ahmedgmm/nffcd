from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class CitadelAuthorityRole(models.Model):
    _name = "citadel.authority.role"
    _description = "Authority Role"
    _order = "company_id, sequence, name"

    name = fields.Char(string="اسم الدور", required=True, translate=True)
    code = fields.Char(string="الرمز", required=True)
    sequence = fields.Integer(string="التسلسل", default=10)
    active = fields.Boolean(string="نشط", default=True)
    company_id = fields.Many2one(
        "res.company", string="الشركة", required=True, default=lambda self: self.env.company, index=True,
    )
    resolver = fields.Selection(
        [
            ("users", "مستخدمون محددون"),
            ("group", "مجموعة صلاحيات"),
            ("manager", "المدير المباشر لمقدم الطلب"),
            ("document", "اللجنة المحددة على المستند"),
        ],
        string="أسلوب تحديد المسؤول", required=True,
        default="users",
    )
    user_ids = fields.Many2many(
        "res.users",
        "citadel_authority_role_user_rel",
        "role_id",
        "user_id",
        string="أصحاب الدور",
        domain="[('share', '=', False)]",
    )
    group_id = fields.Many2one("res.groups", string="مجموعة الدور")
    required_group_id = fields.Many2one(
        "res.groups",
        string="صلاحية التطبيق المطلوبة",
        help="يجب أن ينتمي أصحاب الدور إلى هذه المجموعة ليتمكنوا من الاعتماد.",
    )
    description = fields.Text(string="الوصف")

    _code_company_unique = models.Constraint(
        "UNIQUE(code, company_id)", "The role code must be unique per company.",
    )

    @api.depends("name", "code")
    def _compute_display_name(self):
        for role in self:
            role.display_name = f"[{role.code}] {role.name}" if role.code else role.name

    @api.constrains("resolver", "user_ids", "group_id", "company_id", "required_group_id")
    def _check_resolver(self):
        for role in self:
            if role.resolver == "users" and not role.user_ids:
                raise ValidationError(_("الدور %s من نوع «مستخدمون محددون» ولا يضم أي مستخدم.\n\nالحل: افتح الدور من «الصلاحيات ← الإعدادات ← الأدوار» وأضف مستخدماً واحداً على الأقل.", role.display_name))
            if role.resolver == "group" and not role.group_id:
                raise ValidationError(_("الدور %s من نوع «مجموعة صلاحيات» ولم تُحدد له مجموعة.\n\nالحل: افتح الدور واختر مجموعة الصلاحيات التي يعتمد أعضاؤها.", role.display_name))
            users = role.user_ids if role.resolver == "users" else self.env["res.users"]
            if any(user.share for user in users):
                raise ValidationError(_("الأدوار لا تقبل إلا المستخدمين الداخليين (لا مستخدمي البوابة).\n\nالحل: احذف مستخدمي البوابة من الدور، أو حوّلهم إلى مستخدمين داخليين."))
            if any(role.company_id not in user.company_ids for user in users):
                raise ValidationError(_("بعض أعضاء الدور ليس لهم صلاحية الدخول على جهة الدور.\n\nالحل: من «الإعدادات ← المستخدمون» أضف جهة الدور إلى «الجهات المسموحة» لكل عضو، أو احذفه من الدور."))

    def _citadel_resolve_users(self, document):
        self.ensure_one()
        if self.resolver == "document":
            committee = document._citadel_authority_committee_users()
            users = committee.filtered(
                lambda user: user.active and not user.share and document.company_id in user.company_ids
            )
            if users != committee:
                raise UserError(_(
                    "بعض أعضاء لجنة %(document)s ليس لهم مستخدم نشط له صلاحية على %(company)s: %(users)s."
                    "\n\nالحل: الموظفون: افتح كل موظف واربطه بمستخدم نشط في الجهة، أو استبدله بعضو آخر في اللجنة.",
                    document=document.display_name,
                    company=document.company_id.display_name,
                    users=", ".join((committee - users).mapped("display_name")),
                ))
            return users
        if self.resolver == "manager":
            users = document._citadel_authority_manager_users()
        elif self.resolver == "group":
            users = self.group_id.sudo().all_user_ids
        else:
            users = self.user_ids
        users = users.filtered(
            lambda user: user.active and not user.share and document.company_id in user.company_ids
        )
        if self.required_group_id:
            users = users.filtered(lambda user: self.required_group_id in user.group_ids)
        return users

