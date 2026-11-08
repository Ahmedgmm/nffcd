# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""The posting run: one scoped exemption around every ``_post`` call.

A sub-ledger may seal an entry from inside ``_post``, and a module loaded
after it may then write stored values on that entry once its own
``super()._post`` returns. Every core posting entry point has to finalise
such an entry, while the exemption the run grants must cover only the
entries it is posting: every other sealed entry, its journal items and its
guards stay frozen, and nothing of the run survives past it.
"""

from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.eh_account_base.models.account_move import (
    AccountMove as BaseAccountMove,
)

from .common import EhAccountIntegrationTestCase
from .posting_run_common import (
    POSTING_ENTRY_POINTS,
    later_post_override,
    post_through,
)

WRITTEN_AFTER_SEAL = 'Projection written after the seal'


@tagged('eh_account_base', 'integration', 'post_install', '-at_install')
class TestPostingRun(EhAccountIntegrationTestCase):

    def _entry_values(self, label, amount=100.0):
        return {
            'move_type': 'entry',
            'journal_id': self.journal_misc.id,
            'date': fields.Date.context_today(self.env['res.users']),
            'ref': label,
            'line_ids': [
                Command.create({
                    'account_id': self.account_expense.id,
                    'debit': amount,
                    'name': label,
                }),
                Command.create({
                    'account_id': self.account_cash.id,
                    'credit': amount,
                    'name': label,
                }),
            ],
        }

    def _draft(self, label):
        return self.env['account.move'].create(self._entry_values(label))

    def _sealed_posted(self, label):
        move = self._draft(label)
        move.action_post()
        move._eh_stamp_verified_seal()
        return move

    def test_every_entry_point_finalises_an_entry_sealed_inside_post(self):
        """Seal inside _post, then a later override writes: every path."""
        targets = set()
        core_flags = []

        def seal_then_write(_records, posted):
            mine = posted.filtered(lambda move: move.id in targets)
            if mine:
                # What core put on the posted records reaches every hook:
                # its writes after posting are not manual invoice edits.
                core_flags.append(bool(
                    posted.env.context.get('skip_is_manually_modified'),
                ))
                mine._eh_stamp_verified_seal()
                mine.write({'ref': WRITTEN_AFTER_SEAL})

        with later_post_override(self.env, seal_then_write):
            for entry_point in POSTING_ENTRY_POINTS:
                with self.subTest(entry_point=entry_point):
                    move = self._draft('Posting run %s' % entry_point)
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
        self.assertEqual(core_flags, [True] * len(POSTING_ENTRY_POINTS))

    def test_sealed_draft_posts_through_every_entry_point(self):
        """A draft sealed at creation posts through every path too."""
        for entry_point in POSTING_ENTRY_POINTS:
            with self.subTest(entry_point=entry_point):
                values = dict(
                    self._entry_values('Sealed draft %s' % entry_point),
                    eh_sealed=True,
                )
                if entry_point == 'autopost_cron':
                    values['auto_post'] = 'at_date'
                move = self.env['account.move']._eh_create_sealed(values)
                self.assertEqual(move.state, 'draft')
                post_through(self, entry_point, move)
                self.assertEqual(move.state, 'posted')
                self.assertTrue(move.eh_sealed)

    def test_posting_run_keeps_every_other_sealed_entry_frozen(self):
        """Inside a run, only the entries being posted are exempt."""
        other = self._sealed_posted('Other sealed entry')
        other_line = other.line_ids[:1]
        draft = self._draft('Entry being posted')
        outcomes = {}

        def attempt(label, action):
            try:
                with self.env.cr.savepoint():
                    action()
            except UserError as error:
                outcomes[label] = str(error)
            else:
                outcomes[label] = None

        def probe(_records, posted):
            if draft not in posted:
                return
            run_env = posted.env
            own = draft.with_env(run_env)
            own._eh_stamp_verified_seal()
            other_in_run = other.with_env(run_env)
            other_line_in_run = other_line.with_env(run_env)
            outcomes['own capability'] = (
                own._eh_has_sealed_mutation_capability()
            )
            outcomes['other capability'] = (
                other_in_run._eh_has_sealed_mutation_capability()
            )
            outcomes['mixed capability'] = (
                (own | other_in_run)._eh_has_sealed_mutation_capability()
            )
            outcomes['untargeted capability'] = (
                run_env['account.move']._eh_has_sealed_mutation_capability()
            )
            attempt('own header', lambda: own.write({
                'ref': WRITTEN_AFTER_SEAL,
            }))
            attempt('own line', lambda: own.line_ids[:1].write({
                'name': WRITTEN_AFTER_SEAL,
            }))
            attempt('other header', lambda: other_in_run.write({
                'ref': 'Rewritten inside another run',
            }))
            attempt('other state', lambda: other_in_run.write({
                'state': 'draft',
            }))
            attempt('other line', lambda: other_line_in_run.write({
                'name': 'Rewritten inside another run',
            }))
            attempt('other new line', lambda: run_env[
                'account.move.line'
            ].create({
                'move_id': other.id,
                'account_id': self.account_expense.id,
                'debit': 0.0,
                'credit': 0.0,
                'name': 'Added inside another run',
            }))
            attempt('other unlink', lambda: other_in_run.with_context(
                force_delete=True,
            ).unlink())

        with later_post_override(self.env, probe):
            draft.action_post()

        self.assertIs(outcomes['own capability'], True)
        self.assertIs(outcomes['other capability'], False)
        self.assertIs(outcomes['mixed capability'], False)
        self.assertIs(outcomes['untargeted capability'], False)
        self.assertIsNone(outcomes['own header'])
        self.assertIsNone(outcomes['own line'])
        for label in (
            'other header', 'other state', 'other line', 'other new line',
            'other unlink',
        ):
            with self.subTest(attempt=label):
                self.assertTrue(
                    outcomes[label],
                    '%s of another sealed entry passed inside a posting run'
                    % label,
                )
                self.assertIn(other.name, outcomes[label])
        self.env.invalidate_all()
        self.assertEqual(draft.state, 'posted')
        self.assertTrue(draft.eh_sealed)
        self.assertEqual(draft.ref, WRITTEN_AFTER_SEAL)
        self.assertEqual(other.state, 'posted')
        self.assertEqual(other.ref, 'Other sealed entry')
        self.assertEqual(other_line.name, 'Other sealed entry')
        self.assertEqual(len(other.line_ids), 2)

    def test_posting_run_does_not_outlive_its_frame(self):
        """Nothing of the run leaks into what posting hands back."""
        draft = self._draft('Returned outside the run')
        posted = draft._post(soft=False)
        self.assertEqual(posted, draft)
        self.assertNotIn('eh_post_sealed_internal', posted.env.context)
        self.assertNotIn('eh_post_sealed_ids_internal', posted.env.context)
        self.assertFalse(posted._eh_has_sealed_mutation_capability())

        posted._eh_stamp_verified_seal()
        with self.assertRaises(UserError):
            posted.write({'ref': 'Edited after its posting run'})
        with self.assertRaises(UserError):
            posted.line_ids[:1].write({'name': 'Edited after its run'})
        # The id set means nothing without the in-process capability object,
        # which no client context can carry.
        forged = posted.with_context(
            eh_post_sealed_internal=True,
            eh_post_sealed_ids_internal=posted.ids,
        )
        self.assertFalse(forged._eh_has_sealed_mutation_capability())
        with self.assertRaises(UserError):
            forged.write({'ref': 'Forged posting run'})
        with self.assertRaises(UserError):
            forged.line_ids[:1].write({'name': 'Forged posting run'})

    def test_sealed_draft_posts_before_the_registry_frame_exists(self):
        """Posting while the registry loads, before any hook has run.

        Module data and demo files post while the registry is being built,
        before ``_register_hook`` frames ``_post``. Base's own override in
        the method resolution order still opens the run for everything below
        it, core's writes included. It is called here directly, so modules
        installed above Base in this database play no part in the proof.
        """
        move = self.env['account.move']._eh_create_sealed(dict(
            self._entry_values('Sealed draft while loading'),
            eh_sealed=True,
        ))
        posted = BaseAccountMove._post(move, soft=False)
        self.assertEqual(posted, move)
        self.assertNotIn('eh_post_sealed_internal', posted.env.context)
        self.env.invalidate_all()
        self.assertEqual(move.state, 'posted')
        self.assertTrue(move.eh_sealed)

    def test_registry_frame_is_installed_once_and_removed_cleanly(self):
        model_class = self.env.registry['account.move']
        frame = model_class.__dict__.get('_post')
        self.assertTrue(getattr(frame, '_eh_posting_run_frame', False))
        self.assertFalse(
            getattr(frame.origin, '_eh_posting_run_frame', False),
        )
        self.env['account.move']._register_hook()
        self.assertIs(model_class.__dict__.get('_post'), frame)
        with patch.object(model_class, '_post', frame):
            self.env['account.move']._unregister_hook()
            self.assertNotIn('_post', model_class.__dict__)
            self.env['account.move']._register_hook()
            reframed = model_class.__dict__.get('_post')
            self.assertTrue(
                getattr(reframed, '_eh_posting_run_frame', False),
            )
            self.assertIs(reframed.origin, frame.origin)
        self.assertIs(model_class.__dict__.get('_post'), frame)
