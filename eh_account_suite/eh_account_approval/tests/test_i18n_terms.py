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


@tagged('eh_account_approval', 'post_install', '-at_install')
class TestApprovalTranslations(TransactionCase):

    def test_icon_view_terms_are_translated(self):
        terms = exported_terms(self.env, 'eh_account_approval', icon_view_term)
        self.assertEqual(len(terms), 3)
        self.assertEqual(untranslated_terms('eh_account_approval', terms), [])

    def test_french_kanban_is_translated_once_loaded(self):
        """Load the shipped French file the way a language install does and
        read the view back in French."""
        self.env['res.lang']._activate_lang('fr_FR')
        self.env['ir.module.module']._load_module_terms(
            ['eh_account_approval'], ['fr_FR'], overwrite=True,
        )
        view = self.env.ref('eh_account_approval.view_eh_approval_request_kanban')
        arch = view.with_context(lang='fr_FR').arch_db
        self.assertIn('title="Groupe d\'approbateurs"', arch)
        self.assertIn('title="Date d\'échéance"', arch)
        self.assertIn('Escaladé', arch)
        self.assertIn('data-icon="warning"', arch)
        self.assertNotIn('title="Approver group"', arch)
