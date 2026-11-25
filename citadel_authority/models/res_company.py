from markupsafe import Markup, escape

from odoo import api, fields, models

LETTERHEAD_FIELDS = (
    "citadel_ministry_name", "citadel_ministry_name_en", "citadel_letterhead_address",
    "citadel_letterhead_address_en", "citadel_letterhead_phone", "citadel_letterhead_fax",
    "citadel_purchase_addressee",
)


class ResCompany(models.Model):
    _inherit = "res.company"

    citadel_ministry_name = fields.Char(string="الجهة التابعة لها (عربي)", default="وزارة التضامن الاجتماعي")
    citadel_ministry_name_en = fields.Char(string="الجهة التابعة لها (إنجليزي)", default="Ministry of Social Solidarity")
    citadel_name_en = fields.Char(string="اسم الجهة (إنجليزي)")
    citadel_letterhead_address = fields.Char(string="عنوان الترويسة (عربي)")
    citadel_letterhead_address_en = fields.Char(string="عنوان الترويسة (إنجليزي)")
    citadel_letterhead_phone = fields.Char(string="التليفون")
    citadel_letterhead_fax = fields.Char(string="الفاكس")
    citadel_purchase_addressee = fields.Char(
        string="يُعرض طلب الشراء على", default="السيد / المدير التنفيذي للمؤسسة",
    )

    citadel_letterhead_inherit = fields.Boolean(
        string="استخدام ترويسة الجهة الأم", default=True,
        help="عند التفعيل تُطبع بيانات الترويسة من الجهة الأم، ويظهر اسم هذه الجهة كوحدة تابعة.",
    )
    citadel_letterhead_source_id = fields.Many2one(
        "res.company", string="مصدر الترويسة", compute="_compute_citadel_letterhead_preview",
    )
    citadel_letterhead_preview = fields.Html(
        string="معاينة الترويسة", compute="_compute_citadel_letterhead_preview", sanitize=False,
    )

    def _citadel_letterhead_chain(self):
        """Companies supplying letterhead values, nearest first; inheriting units are skipped."""
        chain = self.env["citadel.authority.policy"]._citadel_company_chain(self)
        return chain.filtered(lambda company: not (company.parent_id and company.citadel_letterhead_inherit))

    @api.depends("parent_id", "logo", "name", "citadel_name_en", "citadel_letterhead_inherit", *LETTERHEAD_FIELDS)
    def _compute_citadel_letterhead_preview(self):
        for company in self:
            lh = company._citadel_letterhead()
            source = company._citadel_letterhead_chain()[:1]
            company.citadel_letterhead_source_id = source.id if source and source != company else False
            company.citadel_letterhead_preview = company._citadel_letterhead_html(lh)

    def _citadel_letterhead_html(self, lh):
        def lines(values):
            return Markup("").join(Markup("<div>%s</div>") % escape(value) for value in values if value)

        ar = lines([lh["ministry"], lh["root"], lh["unit"], lh["address"],
                    lh["phone"] and "تليفون %s" % lh["phone"], lh["fax"] and "فاكس %s" % lh["fax"]])
        tel = " ".join(filter(None, [lh["phone"] and "Tel: %s" % lh["phone"], lh["fax"] and "Fax: %s" % lh["fax"]]))
        en = lines([lh["ministry_en"], lh["root_en"], lh["unit_en"], lh["address_en"], tel])
        logo = Markup("")
        if lh["logo"]:
            data = lh["logo"].decode() if isinstance(lh["logo"], bytes) else lh["logo"]
            logo = Markup('<img src="data:image/png;base64,%s" style="max-height:80px;max-width:100%%;"/>') % data
        addressee = Markup('<div style="margin-top:8px;border-top:1px solid #ccc;padding-top:6px;">يُعرض طلب الشراء على: <b>%s</b></div>') % lh["addressee"] if lh["addressee"] else Markup("")
        return Markup(
            '<div style="border:1px solid #ccc;padding:10px;background:#fff;color:#000;">'
            '<table style="width:100%%;"><tr>'
            '<td dir="rtl" style="width:38%%;text-align:right;font-weight:bold;vertical-align:top;">%s</td>'
            '<td style="width:24%%;text-align:center;vertical-align:middle;">%s</td>'
            '<td dir="ltr" style="width:38%%;text-align:left;font-weight:bold;vertical-align:top;">%s</td>'
            '</tr></table>%s</div>'
        ) % (ar, logo, en, addressee)

    def _citadel_letterhead(self):
        """Letterhead values, falling back to the parent companies (subsidiaries share the foundation header)."""
        self.ensure_one()
        full_chain = self.env["citadel.authority.policy"]._citadel_company_chain(self)
        root = full_chain.filtered(lambda company: not company.parent_id)[:1] or self.sudo()
        chain = self._citadel_letterhead_chain()

        def first(field):
            for company in chain:
                if company[field]:
                    return company[field]
            return False

        return {
            "ministry": first("citadel_ministry_name"),
            "ministry_en": first("citadel_ministry_name_en"),
            "root": root.name,
            "root_en": root.citadel_name_en or "",
            "unit": self.name if self != root else "",
            "unit_en": self.citadel_name_en if self != root else "",
            "address": first("citadel_letterhead_address") or "",
            "address_en": first("citadel_letterhead_address_en") or "",
            "phone": first("citadel_letterhead_phone") or "",
            "fax": first("citadel_letterhead_fax") or "",
            "addressee": first("citadel_purchase_addressee") or "",
            "logo": next((company.logo for company in full_chain if company.logo), False),
        }
