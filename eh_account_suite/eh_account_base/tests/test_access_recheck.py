# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Security re-checks through Base._eh_check_access.

Odoo 20 memoises positive record read checks for the whole transaction,
and a group change on res.users does not clear that memo. The shared
helper is the explicit re-check the suite calls before sensitive work, so
it must see a revocation made earlier in the same transaction.
"""

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import new_test_user, tagged

from .common import EhAccountUnitTestCase


@tagged('eh_account_base', 'post_install', '-at_install')
class TestAccessRecheck(EhAccountUnitTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # account.journal read is granted by Invoicing (or Readonly), not by
        # base.group_user, so removing Invoicing removes the model access.
        cls.invoicing = cls.env.ref('account.group_account_invoice')
        cls.user = new_test_user(
            cls.env,
            login='eh_access_recheck_user',
            groups='base.group_user,account.group_account_invoice',
        )
        cls.journals = cls.env['account.journal'].create([
            {
                'name': 'EH access recheck %s' % code,
                'code': code,
                'type': 'general',
                'company_id': cls.env.company.id,
            }
            for code in ('EHRA', 'EHRB', 'EHRC')
        ])

    def _assert_recheck_denied(self, records):
        """Assert the helper refuses ``records`` for read.

        Odoo's assertRaises(AccessError) clears the whole transaction before
        running its block, which would also drop the read memo this test is
        about, so the refusal is asserted without that reset.
        """
        try:
            records._eh_check_access('read')
        except AccessError:
            return
        self.fail(
            "_eh_check_access('read') passed on %r after the granting group "
            "was revoked in the same transaction." % records
        )

    def _revoke_invoicing(self):
        self.user.write({'group_ids': [Command.unlink(self.invoicing.id)]})
        self.assertFalse(self.user.has_group('account.group_account_invoice'))

    def test_revoked_group_fails_record_recheck(self):
        journal = self.journals[0].with_user(self.user)
        journal._eh_check_access('read')
        # Reading as the user fills the per-transaction read memo exactly as
        # a request that opened the record first would.
        self.assertTrue(journal.name)

        self._revoke_invoicing()

        self._assert_recheck_denied(journal)

    def test_revoked_group_fails_model_level_recheck(self):
        journals = self.env['account.journal'].with_user(self.user)
        journals._eh_check_access('read')

        self._revoke_invoicing()

        self._assert_recheck_denied(journals)

    def test_revoked_group_fails_recheck_of_prefetched_records(self):
        journals = self.journals.with_user(self.user)
        journals._eh_check_access('read')
        self.assertEqual(len(journals.mapped('name')), 3)

        self._revoke_invoicing()

        # Every record re-checks on its own, including records that were
        # memoised through the prefetch of an earlier batch check.
        for journal in journals:
            self._assert_recheck_denied(journal)

    def test_recheck_still_passes_while_the_group_is_kept(self):
        journals = self.journals.with_user(self.user)
        journals._eh_check_access('read')
        self.user.write({'group_ids': [
            Command.link(self.env.ref('base.group_partner_manager').id),
        ]})

        for journal in journals:
            journal._eh_check_access('read')
        journals._eh_check_access('read')
        self.env['account.journal'].with_user(self.user)._eh_check_access(
            'read',
        )
