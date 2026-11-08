# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""The shipped translations match the Odoo 20 portal templates.

Odoo imports view translations by exact source term, so a template term
whose markup changed (the Font Awesome to Material icon swap) is only
translated when the .po files carry the new term.
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eh_account_portal_extra')
class TestPortalTranslations(TransactionCase):

    def _card_arch(self, lang):
        self.env['res.lang']._activate_lang(lang)
        self.env['ir.module.module']._load_module_terms(
            ['eh_account_portal_extra'], [lang], overwrite=True,
        )
        view = self.env.ref('eh_account_portal_extra.portal_my_home_eh_card')
        return view.with_context(lang=lang).arch_db

    def test_portal_card_headings_are_translated(self):
        expected = {
            'de_DE': (
                'Kontostand', 'Kontoauszug herunterladen',
                'Älteste überfällige Rechnung:', 'Kontoauszugsart',
            ),
            'fr_FR': (
                'Solde du compte', 'Télécharger le relevé',
                'Plus ancienne facture en retard :', 'Type de relevé',
            ),
        }
        for lang, headings in expected.items():
            with self.subTest(lang=lang):
                arch = self._card_arch(lang)
                for heading in headings:
                    self.assertIn(heading, arch)
                self.assertNotIn('Account balance', arch)
                self.assertNotIn('Download statement', arch)
                self.assertNotIn('Oldest overdue invoice:', arch)
                self.assertIn('data-icon="balance"', arch)
                self.assertIn('data-icon="picture_as_pdf"', arch)
