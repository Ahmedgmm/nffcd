# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
How the IAS 12 note reads once it is on paper.

The note is a disclosure a customer hands to an auditor, so its figures
have to be typeset the way every other figure in the suite is: grouped
thousands and the reporting currency. They were printed with a bare
'%.2f', which put 333500.00 in a statutory note.
"""

from odoo.tests import tagged

from .test_deferred_tax import TestDeferredTax


@tagged('eh_account_deferred_tax', 'integration', 'post_install', '-at_install')
class TestIas12NoteRender(TestDeferredTax):
    """The printed note carries readable money, not bare floats."""

    def _computed_run_with_a_large_difference(self):
        run = self._run(rate=25.0)
        self.env['eh.deferred.tax.line'].create({
            'run_id': run.id,
            'name': 'Plant and equipment',
            'nature': 'asset',
            'carrying_amount': 1333500.0,
            'tax_base': 1000000.0,
        })
        run.action_compute()
        return run

    def test_note_prints_grouped_amounts_in_the_reporting_currency(self):
        run = self._computed_run_with_a_large_difference()
        report = self.env.ref(
            'eh_account_deferred_tax.action_report_eh_deferred_tax_ias12_note')
        html, ftype = report._render_qweb_html(report.report_name, run.ids)
        rendered = html.decode() if isinstance(html, bytes) else html

        self.assertEqual(ftype, 'html')
        self.assertIn(
            '333,500.00', rendered,
            'the note prints its figures without grouped thousands, so a '
            'reader has to count digits to read a statutory disclosure',
        )
        self.assertNotIn(
            '>333500.00<', rendered,
            'a bare float reached the printed note',
        )
        self.assertIn(
            'data-oe-type="monetary"', rendered,
            'the note has to typeset money the way the rest of the suite '
            'does, through the monetary widget and the run currency',
        )

    def test_note_template_formats_every_amount_as_money(self):
        """No amount escapes the monetary widget.

        Asserted on the template rather than on one rendered run, so a
        column added later cannot quietly go back to a bare float.
        """
        template = self.env.ref(
            'eh_account_deferred_tax.report_deferred_tax_ias12_note')
        arch = template.arch_db or ''
        self.assertNotIn(
            "'%.2f' %", arch,
            'an amount in the IAS 12 note is printed with a bare float '
            'format instead of the monetary widget',
        )
        self.assertGreaterEqual(
            arch.count("'widget': 'monetary'"), 8,
            'every amount column of the note has to be monetary',
        )

    def test_offsetting_note_states_its_amounts_as_money(self):
        """The sentence under the table is a disclosure too.

        It is built in Python and printed verbatim, so it carried bare
        floats onto the page even once the table above it was typeset.
        """
        run = self._computed_run_with_a_large_difference()
        note = run.offsetting_note or ''

        self.assertTrue(note, 'a computed run must state its offsetting')
        self.assertNotIn(
            '83375.00', note,
            'the offsetting sentence prints a bare float in a statutory '
            'disclosure',
        )
        self.assertIn('83,375.00', note)

    def test_offsetting_note_wraps_instead_of_running_off_the_page(self):
        """A long offsetting note has to stay inside the paper.

        The note is preformatted text, which does not wrap on its own, so a
        company with a long name printed past the right edge of the page.
        """
        template = self.env.ref(
            'eh_account_deferred_tax.report_deferred_tax_ias12_note')
        self.assertIn('white-space: pre-wrap', template.arch_db or '')
