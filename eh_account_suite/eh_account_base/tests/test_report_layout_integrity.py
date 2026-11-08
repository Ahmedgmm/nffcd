# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
What a suite report has to get right before the PDF engine sees it.

These tests are deliberately generic: they walk every PDF report of the
accounting suite installed in the database rather than naming templates one
by one, so a report added later is covered the day it ships.

They exist because of a failure mode that no render test catches. The PDF
engine does not convert the page it is given: it keeps only the header,
footer and article subtrees and throws the rest away, and it silently drops
every run of text whose font face it could not embed. A report can
therefore render perfectly valid HTML, raise nothing, produce a PDF of a
plausible size, and still reach the customer with its stylesheet gone, its
invoice rows blank and the company address missing from the letterhead.
That is exactly what happened to eight of these reports: they called the
suite stylesheet outside the layout, the engine discarded it, the body fell
back to the downloadable company font, and the text disappeared.
"""

from lxml import etree

from odoo.tests import tagged

from .common import EhAccountIntegrationTestCase

# The class names the PDF engine keeps. Everything a report emits outside
# these three subtrees is discarded before the engine ever runs.
KEPT_BANDS = ('article', 'header', 'footer')

# A selector only the suite stylesheet defines, used to find it in a page.
STYLESHEET_MARKER = '.eh_pdf_table thead th'

# The stock letterhead is as tall as the company logo plus the address
# list. Odoo reserves this many millimetres for it on its own A4 format,
# and a report that reserves less prints its title over the logo.
STOCK_LETTERHEAD_MM = 52


def band_of(element):
    """The name of the kept subtree this element sits in, or None."""
    node = element
    while node is not None:
        classes = (node.get('class') or '').split()
        for band in KEPT_BANDS:
            if band in classes:
                return band
        node = node.getparent()
    return None


@tagged('eh_account_base', 'integration', 'post_install', '-at_install')
class TestReportLayoutIntegrity(EhAccountIntegrationTestCase):
    """Every suite report survives what the PDF engine does to a page."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.move = cls.post_balanced_move([
            {
                'account': cls.account_receivable,
                'debit': 150.0,
                'partner': cls.partner_a,
                'name': 'Report layout integrity line',
            },
            {
                'account': cls.account_revenue,
                'credit': 150.0,
                'name': 'Report layout integrity counter-leg',
            },
        ])

    def suite_modules(self):
        """eh_account_base and every installed module that builds on it."""
        base = self.env['ir.module.module'].search([
            ('name', '=', 'eh_account_base'),
        ])
        return set((base | base.downstream_dependencies()).mapped('name'))

    def suite_pdf_reports(self):
        """Every installed report of the accounting suite that prints to PDF.

        The suite is eh_account_base and every module that builds on it: they
        share this module's stylesheet, paper formats and letterhead rules.
        Other ERP Heritage product lines installed in the same database (HR,
        logistics, dashboards) print on their own conventions, which their own
        modules test.

        Reports driven by an option set rather than by records are left out:
        they are not printed from a record, they carry their own layout, and
        tools/pdf_probe_20.py renders each of them through its own screen.
        """
        suite_modules = self.suite_modules()
        reports = self.env['ir.actions.report'].search([
            ('report_type', '=', 'qweb-pdf'),
        ])
        found = []
        for report in reports:
            xmlid = report.get_external_id().get(report.id) or ''
            if not xmlid.startswith('eh_'):
                continue
            if xmlid.split('.', 1)[0] not in suite_modules:
                continue
            if report.model == 'eh.account.dynamic.report':
                continue
            found.append((xmlid, report))
        return found

    def test_suite_scope_is_this_base_and_what_builds_on_it(self):
        """The scope above must never go empty or leak past the suite."""
        suite_modules = self.suite_modules()
        self.assertIn('eh_account_base', suite_modules)
        xmlids = [xmlid for xmlid, _report in self.suite_pdf_reports()]
        self.assertIn('eh_account_base.action_report_eh_account_move', xmlids)
        for xmlid in xmlids:
            self.assertIn(xmlid.split('.', 1)[0], suite_modules)

    def rendered_page(self, report, record_ids):
        html, _ftype = report._render_qweb_html(report.report_name, record_ids)
        if isinstance(html, bytes):
            html = html.decode()
        return etree.fromstring('<root>%s</root>' % html,
                                etree.HTMLParser(encoding='utf-8'))

    def test_suite_stylesheet_is_rendered_where_the_engine_keeps_it(self):
        """The stylesheet has to sit inside the layout, not before it.

        A t-call to the stylesheet placed before web.external_layout renders
        it outside the article subtree. The engine keeps only that subtree,
        so the style never reaches the page: the report prints unstyled and,
        having fallen back to the downloadable company font, with its text
        missing. This asserts the stylesheet lands in a kept band.
        """
        page = self.rendered_page(
            self.env.ref('eh_account_base.action_report_eh_account_move'),
            self.move.ids,
        )
        styles = [node for node in page.iter('style')
                  if STYLESHEET_MARKER in (node.text or '')]
        self.assertTrue(
            styles,
            'the Journal Entry report must render the suite stylesheet',
        )
        for style in styles:
            self.assertIn(
                band_of(style), KEPT_BANDS,
                'the suite stylesheet is rendered outside the header, footer '
                'and article subtrees, which is everything the PDF engine '
                'keeps, so it is discarded and the report prints unstyled',
            )

    def test_every_suite_report_arch_calls_the_stylesheet_inside_its_layout(self):
        """The same rule, read off every suite report's own source.

        Rendering each report would need a record of each of their models,
        which a base-module test cannot seed. The ordering is visible in the
        template itself, and it is the ordering that decides whether the
        style survives, so it is asserted there for every report installed
        alongside this one.
        """
        for xmlid, report in self.suite_pdf_reports():
            template = self.env.ref(report.report_name, raise_if_not_found=False)
            if not template:
                continue
            arch = template.arch_db or ''
            # Matched on the call itself, not on the template name: the name
            # also appears in the comments that explain this very rule.
            layout_at = arch.find('t-call="web.external_layout"')
            if layout_at < 0:
                continue  # a report carrying its own layout, such as the
                # dynamic report page, has no band to sit outside of
            for marker in ('t-call="eh_account_base.eh_report_styles"', '<style'):
                style_at = arch.find(marker)
                if style_at < 0:
                    continue
                self.assertGreater(
                    style_at, layout_at,
                    '%s renders %s before it calls web.external_layout, so '
                    'the style lands outside the article subtree and the PDF '
                    'engine discards it' % (xmlid, marker),
                )

    def test_every_suite_report_hands_the_layout_a_company(self):
        """A report must name the company whose letterhead it prints.

        web.external_layout falls back to the active company when no company
        reaches it, so a document belonging to another company prints under
        the wrong name, address and tax number.
        """
        for xmlid, report in self.suite_pdf_reports():
            template = self.env.ref(report.report_name, raise_if_not_found=False)
            if not template:
                continue
            arch = template.arch_db or ''
            if 'web.external_layout' not in arch:
                continue
            self.assertTrue(
                't-set="company"' in arch or 'company="' in arch,
                '%s calls web.external_layout without handing it a company, '
                'so it prints the active company letterhead on another '
                "company's document" % xmlid,
            )

    def test_journal_entry_prints_the_letterhead_of_the_move_company(self):
        """The rule above, proven end to end.

        The bug is the fallback: with no company handed to it the layout
        prints whichever company happens to be active. Printing a document
        of one company while another is active is the everyday way to hit
        it, in a group where an accountant has several companies on the
        switcher, so that is what this reproduces.
        """
        other = self.env['res.company'].create({
            'name': 'Letterhead Proof Company',
        })
        self.env.user.company_ids = [(4, other.id)]
        report = self.env.ref('eh_account_base.action_report_eh_account_move')

        printing = report.with_company(other).with_context(
            allowed_company_ids=[other.id, self.env.company.id])
        html, _ftype = printing._render_qweb_html(
            report.report_name, self.move.ids)
        if isinstance(html, bytes):
            html = html.decode()
        page = etree.fromstring('<root>%s</root>' % html,
                                etree.HTMLParser(encoding='utf-8'))
        header = page.xpath(
            ".//div[contains(concat(' ', normalize-space(@class), ' '),"
            " ' header ')]"
        )
        self.assertTrue(header, 'the report must draw a letterhead band')
        printed = etree.tostring(header[0], encoding='unicode')
        self.assertIn(
            self.move.company_id.name, printed,
            'the letterhead does not name the company the journal entry '
            'belongs to',
        )
        self.assertNotIn(
            other.name, printed,
            'the journal entry printed under the letterhead of whichever '
            'company was active rather than its own',
        )

    def test_suite_reports_pin_installed_faces_on_the_letterhead(self):
        """The letterhead band must not depend on a downloadable font.

        The band is laid out as its own document and the engine fetches the
        company web font over HTTP while it does so. When that fetch does not
        land the engine drops the text set in that face and says nothing, so
        the company address is simply absent from the printed page. Measured
        on a seeded database: the address survived 5 of 8 identical renders
        before the band was pinned, and 8 of 8 after.
        """
        page = self.rendered_page(
            self.env.ref('eh_account_base.action_report_eh_account_move'),
            self.move.ids,
        )
        for band in KEPT_BANDS[1:]:  # header and footer
            nodes = page.xpath(
                ".//div[contains(concat(' ', normalize-space(@class), ' '),"
                " ' %s ')]" % band
            )
            self.assertTrue(nodes, 'the report must draw a %s band' % band)
            printed = etree.tostring(nodes[0], encoding='unicode')
            self.assertIn(
                'font-family', printed,
                'the %s band declares no font family of its own, so it '
                'inherits the downloadable company font and prints blank '
                'whenever the engine cannot embed it' % band,
            )

    def test_suite_paperformats_reserve_the_stock_letterhead_band(self):
        """Reserve the band the stock letterhead actually needs.

        Our reports draw Odoo's own letterhead, which is as tall as the logo
        plus the company address list. Reserving less put the report title on
        top of the logo on every report using these formats.
        """
        for xmlid in ('eh_account_base.paperformat_eh_portrait',
                      'eh_account_base.paperformat_eh_landscape'):
            paperformat = self.env.ref(xmlid)
            self.assertGreaterEqual(
                paperformat.margin_top, STOCK_LETTERHEAD_MM,
                '%s reserves %smm above the body, less than the %smm the '
                'stock letterhead occupies, so the report title prints over '
                'the company logo'
                % (xmlid, paperformat.margin_top, STOCK_LETTERHEAD_MM),
            )
            self.assertGreaterEqual(
                paperformat.header_spacing, STOCK_LETTERHEAD_MM,
                '%s spaces the letterhead %smm from the body, less than the '
                '%smm it occupies' % (xmlid, paperformat.header_spacing,
                                      STOCK_LETTERHEAD_MM),
            )

    def test_every_suite_report_names_its_own_paper(self):
        """A report must not inherit the reader's paper size.

        With no paperformat of its own, a report prints on whatever paper
        the acting company is configured for, so the same document comes out
        A4 for one company and US Letter for another, and a wide schedule is
        squeezed or cropped depending on who pressed Print.
        """
        for xmlid, report in self.suite_pdf_reports():
            self.assertTrue(
                report.paperformat_id,
                '%s names no paper format, so its geometry follows the '
                "reader's company instead of the document" % xmlid,
            )

    def test_printed_strings_use_plain_punctuation(self):
        """House style: no em or en dash in anything a customer reads."""
        for xmlid, report in self.suite_pdf_reports():
            template = self.env.ref(report.report_name, raise_if_not_found=False)
            if not template:
                continue
            # Written as escapes so the rule does not break itself.
            for dash, name in ((chr(0x2014), 'em dash'),
                               (chr(0x2013), 'en dash')):
                self.assertNotIn(
                    dash, template.arch_db or '',
                    '%s prints an %s' % (xmlid, name),
                )
