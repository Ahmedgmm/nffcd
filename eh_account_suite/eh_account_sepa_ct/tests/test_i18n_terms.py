# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""The shipped translations still match the Odoo 20 icon markup of the views.

xml_translate keeps an inline <i> icon in the term, so the icon attributes
are part of the msgid. When the icons moved to Odoo 20 markup the old
msgids stopped matching and these labels and tooltips fell back to English
in every language.
"""

from odoo.tests import TransactionCase, tagged

from odoo.addons.eh_account_base.tests.common import (
    exported_terms,
    icon_view_term,
    untranslated_terms,
)


@tagged('eh_account_sepa_ct', 'post_install', '-at_install')
class TestSepaCtTranslations(TransactionCase):

    def test_icon_view_terms_are_translated(self):
        terms = exported_terms(self.env, 'eh_account_sepa_ct', icon_view_term)
        self.assertEqual(len(terms), 1)
        self.assertEqual(untranslated_terms('eh_account_sepa_ct', terms), [])

    def test_tour_step_keeps_its_translations(self):
        """Dropping the dash from the second tour step changed its msgid;
        the translations must follow it (and carry no dash either)."""
        terms = exported_terms(
            self.env, 'eh_account_sepa_ct',
            lambda ttype, name, source: (
                ttype == 'code'
                and name.endswith('/sepa_ct_tour.js')
                and source.startswith('Second: every')
            ),
        )
        self.assertEqual(len(terms), 1)
        self.assertIn('missing an IBAN; better', next(iter(terms)))
        self.assertEqual(untranslated_terms('eh_account_sepa_ct', terms), [])
