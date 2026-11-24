from odoo import api, fields, models


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

    def _citadel_letterhead(self):
        """Letterhead values, falling back to the parent companies (subsidiaries share the foundation header)."""
        self.ensure_one()
        chain = self.env["citadel.authority.policy"]._citadel_company_chain(self)
        root = chain.filtered(lambda company: not company.parent_id)[:1] or self.sudo()

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
            "logo": next((company.logo for company in chain if company.logo), False),
        }
