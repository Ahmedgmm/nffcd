# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""A generated invoice posts through every core entry point.

The engine seals a generated invoice from inside ``_post``, the moment
posting succeeds. A module loaded after this one (French e-reporting is the
one Odoo ships, auto installed with the French localisation) then writes its
stored projections on the same invoice once its own ``super()._post``
returns. Confirm Entries, the journal dashboard, the validation wizard and
the auto-post cron all reach ``_post`` without ``action_post``; each of them
must still finalise the invoice, and the seal must hold once they are done.
"""

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.eh_account_base.tests.common import (
    EhAccountIntegrationTestCase,
)
from odoo.addons.eh_account_base.tests.posting_run_common import (
    POSTING_ENTRY_POINTS,
    later_post_override,
    post_through,
)

WRITTEN_AFTER_SEAL = 'Projection written after the seal'


@tagged(
    'eh_account_recurring_invoices', 'integration', 'post_install',
    '-at_install',
)
class TestRecurringPostingRun(EhAccountIntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sale_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', '=', 'sale'),
        ], limit=1)
        if not cls.sale_journal:
            cls.sale_journal = cls.env['account.journal'].create({
                'name': 'Sales',
                'code': 'SALE',
                'type': 'sale',
                'company_id': cls.company.id,
            })

    def _generated_draft(self, code):
        today = fields.Date.context_today(self.env['res.users'])
        template = self.env['eh.recurring.invoice.template'].create({
            'name': 'Posting run %s' % code,
            'code': code,
            'partner_id': self.partner_a.id,
            'journal_id': self.sale_journal.id,
            'interval': 1,
            'interval_unit': 'month',
            'start_date': today,
            'next_run_date': today,
            'line_ids': [Command.create({
                'name': 'Support',
                'account_id': self.account_revenue.id,
                'quantity': 1.0,
                'price_unit': 100.0,
            })],
        })
        template.action_activate()
        template.action_generate_now()
        move = template.last_generated_move_id
        self.assertEqual(move.state, 'draft')
        self.assertFalse(move.eh_sealed)
        return move

    def test_generated_invoice_is_finalised_by_every_entry_point(self):
        targets = set()

        def projection_after_super(_records, posted):
            mine = posted.filtered(lambda move: move.id in targets)
            if mine:
                # The engine has already sealed the invoice further down.
                self.assertTrue(all(mine.mapped('eh_sealed')))
                mine.write({'ref': WRITTEN_AFTER_SEAL})

        with later_post_override(self.env, projection_after_super):
            for entry_point in POSTING_ENTRY_POINTS:
                with self.subTest(entry_point=entry_point):
                    move = self._generated_draft(
                        'posting_run_%s' % entry_point,
                    )
                    targets.add(move.id)
                    post_through(self, entry_point, move)
                    self.assertEqual(move.state, 'posted')
                    self.assertTrue(move.eh_sealed)
                    self.assertEqual(move.ref, WRITTEN_AFTER_SEAL)
                    if entry_point == 'autopost_cron':
                        # A refused cron post is rolled back and switched
                        # to auto_post='no'; a finalised one keeps its plan.
                        self.assertEqual(move.auto_post, 'at_date')
                    with self.assertRaises(UserError):
                        move.write({'ref': 'Edited after its posting run'})
