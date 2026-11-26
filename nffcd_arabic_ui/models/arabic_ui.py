from odoo import api, models
from odoo.tools.misc import file_path
from odoo.tools.translate import TranslationImporter

# Non-translatable data whose stored name is English (or a wrong Arabic term).
STOCK_LOCATION_NAMES = {
    "stock.stock_location_suppliers": "الموردون",
    "stock.stock_location_customers": "العملاء",
}
PAYMENT_METHOD_LINE_NAMES = {
    "Manual Payment": "الدفع اليدوي",
    "Manual": "الدفع اليدوي",
    "Checks": "الشيكات",
    "الفحوصات": "الشيكات",
    "Visa": "فيزا",
}


class NffcdArabicUi(models.AbstractModel):
    _name = "nffcd.arabic.ui"
    _description = "واجهة عربية"

    @api.model
    def _apply(self):
        """Force the Arabic overrides over empty/English core translations."""
        if self.env["res.lang"].search_count([("code", "=", "ar_001")]):
            importer = TranslationImporter(self.env.cr, verbose=False)
            importer.load_file(file_path("nffcd_arabic_ui/i18n/ar_001.po"), "ar_001")
            importer.save(overwrite=True, force_overwrite=True)
        for xmlid, name in STOCK_LOCATION_NAMES.items():
            location = self.env.ref(xmlid, raise_if_not_found=False)
            if location and location.name != name:
                location.sudo().name = name
        lines = self.env["account.payment.method.line"].sudo().with_context(active_test=False).search(
            [("name", "in", list(PAYMENT_METHOD_LINE_NAMES))])
        for line in lines:
            line.name = PAYMENT_METHOD_LINE_NAMES[line.name]
        return True
