# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Shared fixtures for tests of the posting run around ``_post``.

A localisation loaded after the whole suite (French e-reporting is the one
Odoo ships) overrides ``_post`` and, once its own ``super()._post`` returns,
writes stored values on the entries it has just posted. Core reaches
``_post`` through several entry points besides ``action_post``. These helpers
emulate that later module and drive each entry point the way the client
does, so a suite module can prove an entry it seals from inside ``_post`` is
finalised by all of them.
"""

from contextlib import contextmanager
from unittest.mock import patch

from odoo import Command

# Every core path that finalises a draft journal entry, as the client or the
# scheduler reaches it.
POSTING_ENTRY_POINTS = (
    'action_post',
    'confirm_entries',
    'dashboard_post_all',
    'validate_wizard',
    'autopost_cron',
)


@contextmanager
def later_post_override(env, after_super):
    """Install ``after_super`` as a ``_post`` override loaded after the suite.

    The override is set on the registry class, the top of the method
    resolution order where a module loaded last sits, and the production
    registry hook is then asked to frame it exactly as it frames every real
    override at startup. ``after_super(records, posted)`` runs once the rest
    of the chain has posted the entries.
    """
    model_class = env.registry['account.move']

    def _post(self, soft=True):
        posted = super(model_class, self)._post(soft=soft)
        after_super(self, posted)
        return posted

    with patch.object(model_class, '_post', _post):
        env['account.move']._register_hook()
        yield


def post_through(case, entry_point, moves):
    """Finalise the draft ``moves`` through one core posting entry point."""
    env = case.env
    if entry_point == 'action_post':
        moves.action_post()
    elif entry_point == 'confirm_entries':
        # Server action "Confirm Entries" on the journal entry list.
        result = moves.action_validate_moves_with_confirmation()
        case.assertFalse(result, 'the entries must post without the wizard')
    elif entry_point == 'dashboard_post_all':
        moves.journal_id.ensure_one()
        result = moves.journal_id.action_post_all_entries()
        case.assertFalse(result, 'the entries must post without the wizard')
    elif entry_point == 'validate_wizard':
        wizard = env['validate.account.move'].with_context(
            active_model='account.move',
            active_ids=moves.ids,
        ).create({'move_ids': [Command.set(moves.ids)]})
        wizard.validate_move()
    elif entry_point == 'autopost_cron':
        # A draft sealed at creation carries its schedule from creation; an
        # ordinary draft is scheduled the way a user does it.
        moves.filtered(lambda move: move.auto_post == 'no').write({
            'auto_post': 'at_date',
        })
        with case.registry_test_mode():
            env.ref(
                'account.ir_cron_auto_post_draft_entry',
            ).method_direct_trigger()
    else:
        raise ValueError(entry_point)
    env.invalidate_all()
