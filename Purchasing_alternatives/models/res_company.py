from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    alternative_committee_approval = fields.Boolean(
        string="اعتماد لجنة البت إلكترونياً",
        default=False,
        help="عند التفعيل يُرسل قرار لجنة البت والمفاضلة لاعتماد الأعضاء إلكترونياً. "
             "عند الإيقاف يوقّع الأعضاء على المحضر ورقياً ويُرفق المحضر الموقع.",
    )


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    alternative_committee_approval = fields.Boolean(
        related="company_id.alternative_committee_approval", readonly=False,
    )
