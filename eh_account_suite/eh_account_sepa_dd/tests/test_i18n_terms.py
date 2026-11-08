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


@tagged('eh_account_sepa_dd', 'post_install', '-at_install')
class TestSepaDdTranslations(TransactionCase):

    def test_icon_view_terms_are_translated(self):
        terms = exported_terms(self.env, 'eh_account_sepa_dd', icon_view_term)
        self.assertEqual(len(terms), 1)
        self.assertEqual(untranslated_terms('eh_account_sepa_dd', terms), [])
