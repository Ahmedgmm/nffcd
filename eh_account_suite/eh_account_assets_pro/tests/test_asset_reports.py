# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Render regression for the two shipped asset PDFs.

Both reports (Asset Register and Asset Card & Schedule) previously
shipped without a render test, and both broke at render time. These
HTML render checks prove the QWeb templates resolve every field and
helper on a valid eh.asset, so any future KeyError or template break is
caught before release. HTML render is used so no wkhtmltopdf binary is
required in CI.
"""

from odoo.tests import tagged

from .common import EhAssetTestCase


@tagged('eh_account_assets_pro', 'integration', 'post_install', '-at_install')
class TestAssetReports(EhAssetTestCase):

    def test_asset_pdf_reports_render(self):
        asset = self._make_asset()

        register = self.env.ref(
            'eh_account_assets_pro.action_report_asset_register',
        )
        html, ftype = register._render_qweb_html(
            register.report_name, asset.ids,
        )
        self.assertEqual(ftype, 'html')
        self.assertTrue(html)
        self.assertIn(b'Asset Register', html)

        card = self.env.ref(
            'eh_account_assets_pro.action_report_asset_card',
        )
        card_html, card_ftype = card._render_qweb_html(
            card.report_name, asset.ids,
        )
        self.assertEqual(card_ftype, 'html')
        self.assertTrue(card_html)

    def test_asset_pdf_reports_print_the_document_company(self):
        # Odoo 20 QWeb always provides ``company`` (the active company), so
        # web.external_layout no longer falls back to the document company
        # by itself. Both reports must still print the asset's company when
        # another company is active.
        asset = self._make_asset()
        other = self.env['res.company'].create({
            'name': 'EH Other Active Company',
        })
        self.env.user.company_ids |= other
        self.assertNotEqual(asset.company_id, other)
        for xmlid in (
            'eh_account_assets_pro.action_report_asset_register',
            'eh_account_assets_pro.action_report_asset_card',
        ):
            with self.subTest(report=xmlid):
                report = self.env.ref(xmlid).with_company(other)
                self.assertEqual(report.env.company, other)
                html, _ftype = report._render_qweb_html(
                    report.report_name, asset.ids,
                )
                self.assertIn(asset.company_id.name.encode(), html)
                self.assertNotIn(other.name.encode(), html)
