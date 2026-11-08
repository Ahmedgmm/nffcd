# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""The posting schedule of a sealed draft entry.

Held-for-sale write-downs, like every sub-ledger figure, are created through
Base's sealed corridor, which freezes the draft at once. A sealed draft sent
through Confirm Entries without Force on a future date is scheduled by core
(auto_post='at_date') inside its posting run. Core then stops that schedule
outside any posting run in two places: the Validate Entries wizard with
Force ticked, so the entry posts now, and the auto-post cron's error handler
for an entry that cannot post. The seal lets exactly that through; a figure,
a recurrence and a posted entry stay frozen.
"""

from datetime import datetime, time, timedelta

from freezegun import freeze_time

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.eh_account_base.tests.common import (
    EhAccountIntegrationTestCase,
)

REFUSED_POST = 'could not be posted'


@tagged('eh_account_held_for_sale', 'post_install', '-at_install')
class TestSealedDraftSchedule(EhAccountIntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.asset = cls._ensure_account(
            cls.env, '1700', 'Assets Held for Sale', 'asset_current')
        cls.impairment = cls._ensure_account(
            cls.env, '5170', 'Held-for-sale Impairment', 'expense')
        cls.manager = cls.env['res.users'].create({
            'name': 'HFS Schedule Manager',
            'login': 'eh_hfs_schedule_manager',
            'email': 'eh_hfs_schedule_manager@example.com',
            'company_id': cls.company.id,
            'company_ids': [(6, 0, cls.company.ids)],
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('eh_account_base.group_eh_manager').id,
            ])],
        })
        cls.due_date = fields.Date.today() + timedelta(days=5)

    def _validate(self, moves, force):
        wizard = self.env['validate.account.move'].with_user(
            self.manager,
        ).with_context(
            active_model='account.move',
            active_ids=moves.ids,
        ).create({'force_post': force})
        self.assertFalse(wizard.env.su)
        self.assertEqual(wizard.move_ids, moves)
        self.assertTrue(wizard.display_force_post)
        wizard.validate_move()
        self.env.invalidate_all()

    def _scheduled_sealed_writedown(self):
        """A sealed write-down draft, then Confirm Entries without Force."""
        move = self.env['account.move']._eh_create_sealed({
            'move_type': 'entry',
            'journal_id': self.journal_misc.id,
            'date': self.due_date,
            'ref': 'Scheduled held-for-sale write-down',
            'eh_sealed': True,
            'line_ids': [
                Command.create({
                    'account_id': self.impairment.id,
                    'debit': 200.0,
                    'name': 'Held-for-sale write-down',
                }),
                Command.create({
                    'account_id': self.asset.id,
                    'credit': 200.0,
                    'name': 'Remeasure to FVLCTS',
                }),
            ],
        })
        self.assertEqual(move.state, 'draft')
        self.assertEqual(move.auto_post, 'no')
        self._validate(move, force=False)
        self.assertEqual(move.state, 'draft')
        self.assertEqual(move.auto_post, 'at_date')
        self.assertTrue(move.eh_sealed)
        return move

    def _due_ordinary_entry(self, label):
        return self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal_misc.id,
            'date': self.due_date,
            'auto_post': 'at_date',
            'ref': label,
            'line_ids': [
                Command.create({
                    'account_id': self.account_expense.id,
                    'debit': 30.0,
                    'name': label,
                }),
                Command.create({
                    'account_id': self.account_cash.id,
                    'credit': 30.0,
                    'name': label,
                }),
            ],
        })

    def _run_autopost_cron_on_due_date(self):
        # Noon keeps the cron's context_today on the due date in any timezone.
        with freeze_time(datetime.combine(self.due_date, time(12, 0))), \
                self.registry_test_mode():
            result = self.env.ref(
                'account.ir_cron_auto_post_draft_entry',
            ).method_direct_trigger()
        self.env.invalidate_all()
        return result

    def _refusal_messages(self, move):
        return move.message_ids.filtered(
            lambda message: REFUSED_POST in (message.body or ''))

    def test_force_posts_a_scheduled_sealed_draft_now(self):
        """Validate Entries with Force posts the sealed draft now."""
        move = self._scheduled_sealed_writedown()
        self._validate(move, force=True)
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.auto_post, 'no')
        self.assertEqual(move.date, self.due_date)
        self.assertTrue(move.eh_sealed)
        self.assertEqual(
            sorted(move.line_ids.mapped('balance')), [-200.0, 200.0])
        # Posted, its schedule is history like every other figure.
        with self.assertRaises(UserError):
            move.with_user(self.manager).write({'auto_post': 'no'})

    def test_cron_stops_a_sealed_draft_it_cannot_post(self):
        """A refused cron post stops the schedule and the cron carries on."""
        ordinary = self._due_ordinary_entry('Due after the refused entry')
        move = self._scheduled_sealed_writedown()
        # Drafts of one date come up newest first: the refusal comes first.
        self.assertGreater(move.id, ordinary.id)
        # The chart was tidied before the due date: posting now fails on
        # the archived account, which only a person can resolve.
        self.impairment.active = False

        result = self._run_autopost_cron_on_due_date()

        self.assertIs(result, True, 'the auto-post cron failed')
        self.assertEqual(move.state, 'draft')
        self.assertEqual(move.auto_post, 'no')
        self.assertTrue(move.eh_sealed)
        self.assertTrue(self._refusal_messages(move))
        self.assertEqual(
            sorted(move.line_ids.mapped('balance')), [-200.0, 200.0])
        self.assertEqual(ordinary.state, 'posted')

        # Stopped, the entry leaves the queue: a second run neither fails
        # nor logs the refusal again.
        self.assertIs(self._run_autopost_cron_on_due_date(), True)
        self.assertEqual(len(self._refusal_messages(move)), 1)

    def test_cron_stops_a_quarantined_legacy_draft(self):
        """A legacy draft never posts; the cron stops asking."""
        ordinary = self._due_ordinary_entry('Due after the legacy draft')
        legacy = self._due_ordinary_entry('Quarantined legacy draft')
        self.assertGreater(legacy.id, ordinary.id)
        # Only an upgrade sets the quarantine, never a write.
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE account_move SET eh_legacy_unverified_seal = TRUE "
            "WHERE id = %s", (legacy.id,))
        self.env.invalidate_all()
        self.assertTrue(legacy.eh_legacy_unverified_seal)

        result = self._run_autopost_cron_on_due_date()

        self.assertIs(result, True, 'the auto-post cron failed')
        self.assertEqual(legacy.state, 'draft')
        self.assertEqual(legacy.auto_post, 'no')
        self.assertTrue(legacy.eh_legacy_unverified_seal)
        self.assertTrue(self._refusal_messages(legacy))
        self.assertEqual(ordinary.state, 'posted')

    def test_only_stopping_a_draft_schedule_passes_the_seal(self):
        """Any other schedule change on a sealed draft is refused."""
        move = self._scheduled_sealed_writedown()
        refused = (
            {'auto_post': 'monthly'},
            {'auto_post': 'quarterly'},
            {'auto_post': 'yearly'},
            {'auto_post': 'at_date'},
            {'auto_post': 'no', 'ref': 'Stopped and renamed'},
            {'auto_post': 'no', 'date': self.due_date + timedelta(days=1)},
            {'auto_post_until': self.due_date + timedelta(days=90)},
        )
        for vals in refused:
            with self.subTest(vals=vals), self.assertRaises(UserError):
                move.with_user(self.manager).write(vals)
        self.assertEqual(move.auto_post, 'at_date')
        move.with_user(self.manager).write({'auto_post': 'no'})
        self.assertEqual(move.auto_post, 'no')
        self.assertEqual(move.state, 'draft')
        self.assertTrue(move.eh_sealed)
