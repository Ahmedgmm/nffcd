# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Regression: the state machine is enforced in the ORM, not just the UI.

A plain interactive user must not be able to RPC-write ``state`` straight to
a posted value, skipping ``action_classify`` / ``action_sell`` and the
journal entry they post. The ``eh.workflow.guard`` mixin blocks any direct
write to a guarded field unless it originates from the record's own action.
"""

import json
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.service.model import call_kw
from odoo.tests import tagged

from odoo.addons.eh_account_base.tests.common import (
    EhAccountIntegrationTestCase,
)


@tagged('eh_account_held_for_sale', 'post_install', '-at_install')
class TestWorkflowGuard(EhAccountIntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.asset = cls._ensure_account(
            cls.env, '1700', 'Assets Held for Sale', 'asset_current')
        cls.impairment = cls._ensure_account(
            cls.env, '5170', 'Held-for-sale Impairment', 'expense')
        cls.env.user.group_ids |= cls.env.ref(
            'eh_account_base.group_eh_manager')
        # A non-superuser, non-manager internal user. The test env itself runs
        # as superuser, for which the guard is deliberately inert, so the
        # guarded write must be attempted through with_user(this user).
        cls.plain_user = cls.env['res.users'].create({
            'name': 'HFS Plain User',
            'login': 'eh_hfs_plain_user',
            'email': 'eh_hfs_plain_user@example.com',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.eh_user = cls.env['res.users'].create({
            'name': 'HFS Accounting User',
            'login': 'eh_hfs_accounting_user',
            'email': 'eh_hfs_accounting_user@example.com',
            'company_id': cls.company.id,
            'company_ids': [(6, 0, cls.company.ids)],
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('eh_account_base.group_eh_user').id,
            ])],
        })
        cls.core_account_manager = cls.env['res.users'].create({
            'name': 'Core Accounting Manager without HFS access',
            'login': 'eh_hfs_core_account_manager',
            'email': 'eh_hfs_core_account_manager@example.com',
            'company_id': cls.company.id,
            'company_ids': [(6, 0, cls.company.ids)],
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('account.group_account_manager').id,
            ])],
        })
        cls.eh_manager = cls.env['res.users'].create({
            'name': 'HFS Accounting Manager',
            'login': 'eh_hfs_accounting_manager',
            'email': 'eh_hfs_accounting_manager@example.com',
            'company_id': cls.company.id,
            'company_ids': [(6, 0, cls.company.ids)],
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('eh_account_base.group_eh_manager').id,
            ])],
        })
        cls.billing_user = cls.env['res.users'].create({
            'name': 'HFS Billing User',
            'login': 'eh_hfs_billing_user',
            'email': 'eh_hfs_billing_user@example.com',
            'company_id': cls.company.id,
            'company_ids': [(6, 0, cls.company.ids)],
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('account.group_account_invoice').id,
            ])],
        })

    def _item(self, **extra):
        vals = {
            'name': '/',
            'carrying_amount': 1000.0,
            'fair_value_less_costs': 800.0,
            'asset_account_id': self.asset.id,
            'impairment_account_id': self.impairment.id,
            'journal_id': self.journal_misc.id,
        }
        vals.update(extra)
        return self.env['eh.held.for.sale'].create(vals)

    def _group(self):
        return self.env['eh.disposal.group'].create({
            'name': '/',
            'fair_value_less_costs': 800.0,
            'impairment_account_id': self.impairment.id,
            'asset_account_id': self.asset.id,
            'journal_id': self.journal_misc.id,
            'line_ids': [(0, 0, {
                'name': 'Member A',
                'carrying_amount': 1000.0,
                'account_id': self.asset.id,
            })],
        })

    def test_held_for_sale_state_write_blocked_for_plain_user(self):
        item = self.env['eh.held.for.sale'].create({
            'name': '/',
            'carrying_amount': 1000.0,
            'fair_value_less_costs': 800.0,
            'asset_account_id': self.asset.id,
            'impairment_account_id': self.impairment.id,
            'journal_id': self.journal_misc.id,
        })
        self.assertEqual(item.state, 'draft')
        # RPC-writing the state to 'held' would skip the write-down journal
        # entry that action_classify posts. The guard must refuse it.
        with self.assertRaises(AccessError):
            item.with_user(self.plain_user).write({'state': 'held'})
        # And the value must not have moved.
        self.assertEqual(item.state, 'draft')

    def test_disposal_group_state_write_blocked_for_plain_user(self):
        group = self.env['eh.disposal.group'].create({
            'name': '/',
            'fair_value_less_costs': 800.0,
            'impairment_account_id': self.impairment.id,
            'asset_account_id': self.asset.id,
            'journal_id': self.journal_misc.id,
        })
        self.assertEqual(group.state, 'draft')
        with self.assertRaises(AccessError):
            group.with_user(self.plain_user).write({'state': 'sold'})
        self.assertEqual(group.state, 'draft')

    def test_classified_single_basis_and_pause_marker_are_immutable(self):
        item = self._item()
        item.action_classify()
        with self.assertRaises(UserError):
            item.with_user(self.eh_user).write({
                'classification_date': '2026-01-01',
            })
        with self.assertRaises(AccessError):
            item.with_user(self.eh_user).write({
                'asset_paused_by_hfs': True,
            })

    def test_classified_group_and_member_evidence_are_immutable(self):
        group = self._group()
        group.action_classify()
        line = group.line_ids
        with self.assertRaises(UserError):
            line.with_user(self.eh_user).write({
                'asset_paused_by_group': True,
            })
        with self.assertRaises(UserError):
            line.with_user(self.eh_user).write({
                'account_id': self.impairment.id,
            })
        with self.assertRaises(UserError):
            group.with_user(self.eh_user).write({
                'classification_date': '2026-01-01',
            })

    def test_eh_user_can_update_scope_without_chart_write_access(self):
        """Validating an HFS record needs read, not configuration-write,
        access to the referenced discontinued-operation accounts."""
        item = self._item(
            is_discontinued=True,
            discontinued_pl_account_ids=[(6, 0, self.impairment.ids)],
        )
        move = self.post_balanced_move([
            {'account': self.impairment, 'debit': 10.0},
            {'account': self.account_cash, 'credit': 10.0},
        ], date='2026-01-01')
        candidate = move.line_ids.filtered(
            lambda line: line.account_id == self.impairment)
        item.discontinued_candidate_move_line_ids = [(6, 0, candidate.ids)]
        item.action_tag_discontinued()

        self.assertFalse(
            self.env['account.account'].with_user(
                self.eh_user).browse().has_access('write')
        )
        item.with_user(self.eh_user).write({
            'discontinued_candidate_move_line_ids': [(6, 0, candidate.ids)],
        })
        self.assertEqual(item.discontinued_candidate_move_line_ids, candidate)

        group = self._group()
        group.line_ids.with_user(self.eh_user).write({
            'pl_account_id': self.impairment.id,
        })
        self.assertEqual(group.line_ids.pl_account_id, self.impairment)

    def test_move_provenance_is_immutable(self):
        item = self._item()
        item.action_classify()
        move = item.move_ids[:1]
        self.assertTrue(move)
        with self.assertRaises(AccessError):
            move.write({'eh_held_for_sale_id': False})

    def test_core_accountant_without_hfs_acl_can_create_ordinary_bill(self):
        """HFS evidence guards must not break standard accounting flows."""
        user = self.core_account_manager
        self.assertFalse(user.has_group('eh_account_base.group_eh_user'))
        bill = self.env['account.move'].with_user(user).with_company(
            self.company,
        ).create({
            'move_type': 'in_invoice',
            'company_id': self.company.id,
            'partner_id': self.partner_a.id,
            'journal_id': self.journal_purchase.id,
            'invoice_date': '2026-01-15',
            'invoice_line_ids': [(0, 0, {
                'name': 'Ordinary vendor charge',
                'account_id': self.account_expense.id,
                'quantity': 1.0,
                'price_unit': 25.0,
            })],
        })
        self.assertTrue(bill.invoice_line_ids)

    def test_core_accountant_cannot_edit_frozen_discontinued_line(self):
        """Narrow lookup elevation must preserve frozen-line enforcement."""
        item = self._item(
            is_discontinued=True,
            discontinued_pl_account_ids=[(6, 0, self.impairment.ids)],
        )
        move = self.post_balanced_move([
            {'account': self.impairment, 'debit': 10.0},
            {'account': self.account_cash, 'credit': 10.0},
        ], date='2026-01-01')
        candidate = move.line_ids.filtered(
            lambda line: line.account_id == self.impairment,
        )
        item.discontinued_candidate_move_line_ids = [(6, 0, candidate.ids)]
        item.action_tag_discontinued()

        with self.assertRaisesRegex(
                UserError, 'frozen discontinued-operation'):
            candidate.with_user(self.core_account_manager).write({
                'account_id': self.account_cash.id,
            })

    def _tagged_discontinued_line(self):
        item = self._item(
            is_discontinued=True,
            discontinued_pl_account_ids=[(6, 0, self.impairment.ids)],
        )
        move = self.post_balanced_move([
            {'account': self.impairment, 'debit': 10.0},
            {'account': self.account_cash, 'credit': 10.0},
        ], date='2026-01-01')
        candidate = move.line_ids.filtered(
            lambda line: line.account_id == self.impairment,
        )
        item.discontinued_candidate_move_line_ids = [(6, 0, candidate.ids)]
        item.action_tag_discontinued()
        return item, candidate

    def test_core_accountant_can_duplicate_an_ordinary_entry(self):
        """Duplicating an entry needs no discontinued-operation capability.

        Both evidence relations are copy=True so a reversal inherits its
        scope, and copy_data returns them as Command.set(ids). For ordinary
        journal items that is an empty Command.set, which names no record
        and must not read as caller-supplied scope.
        """
        user = self.core_account_manager
        Move = self.env['account.move'].with_user(user).with_company(
            self.company,
        )
        bill = Move.create({
            'move_type': 'in_invoice',
            'company_id': self.company.id,
            'partner_id': self.partner_a.id,
            'journal_id': self.journal_purchase.id,
            'invoice_date': '2026-01-15',
            'invoice_line_ids': [(0, 0, {
                'name': 'Ordinary vendor charge',
                'account_id': self.account_expense.id,
                'quantity': 1.0,
                'price_unit': 25.0,
            })],
        })
        entry = Move.browse(self.post_balanced_move([
            {'account': self.account_expense, 'debit': 40.0},
            {'account': self.account_cash, 'credit': 40.0},
        ], date='2026-01-01').id)
        copied_line = entry.line_ids[:1].copy_data()[0]
        self.assertEqual(
            copied_line['eh_discontinued_hfs_ids'], [Command.set([])])
        self.assertEqual(
            copied_line['eh_discontinued_group_ids'], [Command.set([])])
        for original in (bill, entry):
            with self.subTest(move_type=original.move_type):
                duplicate = original.copy()
                self.assertEqual(duplicate.state, 'draft')
                self.assertEqual(
                    len(duplicate.line_ids), len(original.line_ids))
                self.assertFalse(
                    duplicate.line_ids._eh_discontinued_scoped_lines())

    def test_only_a_command_naming_a_record_is_line_scope(self):
        """Empty evidence commands pass; any command that links is refused."""
        item = self._item()
        group = self._group()

        def create_entry(field_name, value):
            return self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': self.journal_misc.id,
                'date': '2026-01-01',
                'line_ids': [
                    Command.create({
                        'account_id': self.impairment.id,
                        'debit': 5.0,
                        'name': 'Scope probe',
                        field_name: value,
                    }),
                    Command.create({
                        'account_id': self.account_cash.id,
                        'credit': 5.0,
                        'name': 'Scope probe',
                    }),
                ],
            })

        for field_name in (
                'eh_discontinued_hfs_ids', 'eh_discontinued_group_ids'):
            for value in (
                    [], False, [Command.set([])], [Command.clear()],
                    [Command.clear(), Command.set([])]):
                with self.subTest(field=field_name, value=value):
                    move = create_entry(field_name, value)
                    self.assertFalse(
                        move.line_ids._eh_discontinued_scoped_lines())
        for field_name, record in (
                ('eh_discontinued_hfs_ids', item),
                ('eh_discontinued_group_ids', group)):
            for value in (
                    [Command.set(record.ids)], [Command.link(record.id)],
                    [Command.clear(), Command.link(record.id)],
                    [record.id]):
                with self.subTest(field=field_name, value=value), \
                        self.assertRaisesRegex(AccessError, 'engine-owned'):
                    create_entry(field_name, value)

    def test_defaults_cannot_attach_line_scope(self):
        """Context and ir.default values never reach the scope relations."""
        item = self._item()
        draft = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal_misc.id,
            'date': '2026-01-01',
        })
        line_vals = {
            'move_id': draft.id,
            'account_id': self.impairment.id,
            'debit': 0.0,
            'credit': 0.0,
            'name': 'Default probe',
        }
        Line = self.env['account.move.line'].with_context(
            check_move_validity=False,
        )
        from_context = Line.with_context(
            default_eh_discontinued_hfs_ids=[Command.set(item.ids)],
        ).create(dict(line_vals))
        self.assertFalse(from_context._eh_discontinued_scoped_lines())
        self.env['ir.default'].set(
            'account.move.line', 'eh_discontinued_hfs_ids', item.ids,
        )
        from_ir_default = Line.create(dict(line_vals))
        self.assertFalse(from_ir_default._eh_discontinued_scoped_lines())

    def test_discontinued_scope_survives_reversal_and_stays_immutable(self):
        """Reversal inherits the real scope, and no write can clear it."""
        _item, line = self._tagged_discontinued_line()
        self.assertEqual(line._eh_discontinued_scoped_lines(), line)
        for value in ([Command.set([])], [Command.clear()]):
            with self.subTest(value=value), \
                    self.assertRaisesRegex(AccessError, 'immutable'):
                line.write({'eh_discontinued_hfs_ids': value})
        reversal = line.move_id._reverse_moves(cancel=False)
        self.assertNotIn(
            'eh_discontinued_line_capability', reversal.env.context)
        reversed_line = reversal.line_ids.filtered(
            lambda rev: rev.account_id == self.impairment,
        )
        self.assertEqual(len(reversed_line), 1)
        self.assertEqual(reversal.state, 'draft')
        # Core copies the entry and then writes the negated balance onto
        # the copy; the reversal must carry both the scope and that sign.
        self.assertEqual(reversed_line.balance, -line.balance)
        self.assertEqual(
            reversed_line._eh_discontinued_scoped_lines(), reversed_line)
        self.assertEqual(
            reversed_line.sudo().eh_discontinued_hfs_ids,
            line.sudo().eh_discontinued_hfs_ids,
        )
        # Once the reversal is built, its scoped item is frozen too.
        with self.assertRaisesRegex(
                UserError, 'frozen discontinued-operation'):
            reversed_line.write({'balance': -1.0})
        reversal.action_post()
        self.assertEqual(reversal.state, 'posted')
        self.assertEqual(
            reversed_line._eh_discontinued_scoped_lines(), reversed_line)

        cancelled = self._tagged_discontinued_line()[1]
        counter = cancelled.move_id._reverse_moves(cancel=True)
        self.assertEqual(counter.state, 'posted')
        self.assertEqual(
            counter.line_ids._eh_discontinued_scoped_lines().balance,
            -cancelled.balance,
        )

    # ---- who reverses or duplicates a scoped entry ----

    def _discontinued_actors(self):
        """Superuser, an EH user who reads the evidence, and one who cannot.

        Odoo 20's copy_data copies a many2many only as far as the caller can
        read it, so the core accountant, who has no EH group, gets an empty
        Command.set for a journal item that IS in a discontinued scope.
        """
        core = self.core_account_manager
        self.assertFalse(core.has_group('eh_account_base.group_eh_user'))
        for model_name in ('eh.held.for.sale', 'eh.disposal.group'):
            self.assertFalse(
                self.env[model_name].with_user(core).has_access('read'))
            self.assertTrue(
                self.env[model_name].with_user(self.eh_user).has_access(
                    'read'))
        return (
            ('superuser', False),
            ('eh_user', self.eh_user),
            ('core_accountant', core),
        )

    @staticmethod
    def _acting(records, user):
        return records.with_user(user) if user else records

    def _scoped_move(self, move_type):
        """A posted entry or customer invoice with two scoped P&L items.

        One item belongs to a held-for-sale item, the other to a disposal
        group, so both evidence relations are exercised.
        """
        other_income = self._ensure_account(
            self.env, '4910', 'Discontinued Other Income', 'income_other')
        item = self._item(
            is_discontinued=True,
            discontinued_pl_account_ids=[(6, 0, self.impairment.ids)],
        )
        group = self.env['eh.disposal.group'].create({
            'name': '/',
            'fair_value_less_costs': 800.0,
            'impairment_account_id': self.impairment.id,
            'asset_account_id': self.asset.id,
            'journal_id': self.journal_misc.id,
            'is_discontinued': True,
            'line_ids': [(0, 0, {
                'name': 'Member A',
                'carrying_amount': 1000.0,
                'account_id': self.asset.id,
            })],
        })
        if move_type == 'entry':
            move = self.post_balanced_move([
                {'account': self.impairment, 'debit': 10.0},
                {'account': other_income, 'credit': 4.0},
                {'account': self.account_cash, 'credit': 6.0},
            ], date='2026-01-01')
            item_account = self.impairment
        else:
            move = self.env['account.move'].create({
                'move_type': move_type,
                'partner_id': self.partner_a.id,
                'journal_id': self.journal_sale.id,
                'invoice_date': '2026-01-01',
                'date': '2026-01-01',
                'invoice_line_ids': [
                    Command.create({
                        'name': 'Discontinued revenue',
                        'account_id': self.account_revenue.id,
                        'quantity': 1.0,
                        'price_unit': 100.0,
                        'tax_ids': [Command.clear()],
                    }),
                    Command.create({
                        'name': 'Discontinued other income',
                        'account_id': other_income.id,
                        'quantity': 1.0,
                        'price_unit': 40.0,
                        'tax_ids': [Command.clear()],
                    }),
                ],
            })
            move.action_post()
            item_account = self.account_revenue
        item_line = move.line_ids.filtered(
            lambda line: line.account_id == item_account)
        group_line = move.line_ids.filtered(
            lambda line: line.account_id == other_income)
        item.discontinued_candidate_move_line_ids = [(6, 0, item_line.ids)]
        item.action_tag_discontinued()
        group.discontinued_candidate_move_line_ids = [
            (6, 0, group_line.ids)]
        group.action_tag_discontinued()
        self.assertEqual(
            move.line_ids._eh_discontinued_scoped_lines(),
            item_line | group_line,
        )
        return move

    def _discontinued_total(self):
        """IFRS 5.33 pre-tax discontinued result for the whole test span."""
        return self.env['eh.disposal.group'].eh_discontinued_pl_amount(
            '2026-01-01',
            fields.Date.add(fields.Date.today(), years=1),
            company=self.company,
        )

    def _assert_counter_scope(self, source, counter):
        """Each scoped source item has one counter item with its scope."""
        source_scoped = source.line_ids._eh_discontinued_scoped_lines()
        counter_scoped = counter.line_ids._eh_discontinued_scoped_lines()
        self.assertEqual(len(source_scoped), 2)
        self.assertEqual(len(counter_scoped), len(source_scoped))
        for line in source_scoped.sudo():
            twin = counter_scoped.sudo().filtered(
                lambda rev: rev.account_id == line.account_id)
            self.assertEqual(len(twin), 1)
            self.assertEqual(
                twin.eh_discontinued_hfs_ids, line.eh_discontinued_hfs_ids)
            self.assertEqual(
                twin.eh_discontinued_group_ids,
                line.eh_discontinued_group_ids,
            )
            self.assertAlmostEqual(twin.balance, -line.balance)

    def test_reverse_moves_carries_scope_whoever_reverses(self):
        """_reverse_moves gives the counter entry the source's exact scope.

        The result must not depend on who reverses: a caller who cannot read
        the held-for-sale records still produces a scoped counter entry, so
        the discontinued result nets to what it was before the source.
        """
        for label, user in self._discontinued_actors():
            for move_type in ('entry', 'out_invoice'):
                for cancel in (False, True):
                    with self.subTest(
                            actor=label, move_type=move_type, cancel=cancel):
                        before = self._discontinued_total()
                        source = self._scoped_move(move_type)
                        self.assertNotAlmostEqual(
                            self._discontinued_total(), before)
                        counter = self._acting(
                            source, user)._reverse_moves(cancel=cancel)
                        self.assertEqual(len(counter), 1)
                        self.assertEqual(counter.reversed_entry_id, source)
                        self._assert_counter_scope(source, counter)
                        if counter.state == 'draft':
                            counter.action_post()
                        self.assertEqual(counter.state, 'posted')
                        self._assert_counter_scope(source, counter)
                        self.assertAlmostEqual(
                            self._discontinued_total(), before)

    def test_reversal_wizard_carries_scope_whoever_reverses(self):
        """The Reverse and Credit Note wizard behaves like _reverse_moves."""
        for label, user in self._discontinued_actors():
            for move_type in ('entry', 'out_invoice'):
                with self.subTest(actor=label, move_type=move_type):
                    before = self._discontinued_total()
                    source = self._scoped_move(move_type)
                    wizard = self._acting(
                        self.env['account.move.reversal'], user,
                    ).with_context(
                        active_model='account.move', active_ids=source.ids,
                    ).create({
                        'reason': 'Discontinued scope probe',
                        'date': '2026-01-01',
                        'journal_id': source.journal_id.id,
                    })
                    wizard.refund_moves()
                    counter = wizard.new_move_ids
                    self.assertEqual(len(counter), 1)
                    self.assertEqual(counter.reversed_entry_id, source)
                    self._assert_counter_scope(source, counter)
                    if counter.state == 'draft':
                        counter.action_post()
                    self.assertEqual(counter.state, 'posted')
                    self._assert_counter_scope(source, counter)
                    self.assertAlmostEqual(
                        self._discontinued_total(), before)

    def test_duplicating_a_scoped_entry_is_refused_whoever_asks(self):
        """A duplicate is a new entry, never a silent unscoped copy.

        Duplicate, and the wizard's reverse and create invoice, which
        duplicates the source after reversing it, are refused for every
        caller, with nothing left behind. An ordinary entry of the same shape
        still duplicates, so the refusal is tied to the scope alone.
        """
        Move = self.env['account.move']
        for label, user in self._discontinued_actors():
            for move_type in ('entry', 'out_invoice'):
                with self.subTest(actor=label, move_type=move_type):
                    source = self._scoped_move(move_type)
                    count = Move.search_count([])
                    with self.assertRaisesRegex(
                            AccessError, 'cannot be duplicated'), \
                            self.env.cr.savepoint():
                        self._acting(source, user).copy()
                    self.assertEqual(Move.search_count([]), count)
                    if move_type != 'out_invoice':
                        continue
                    wizard = self._acting(
                        self.env['account.move.reversal'], user,
                    ).with_context(
                        active_model='account.move', active_ids=source.ids,
                    ).create({
                        'date': '2026-01-01',
                        'journal_id': source.journal_id.id,
                    })
                    with self.assertRaisesRegex(
                            AccessError, 'cannot be duplicated'), \
                            self.env.cr.savepoint():
                        wizard.modify_moves()
                    self.assertEqual(Move.search_count([]), count)
                    self.assertFalse(source.reversal_move_ids)
                    self.assertEqual(source.state, 'posted')

                    ordinary = self._acting(Move, user).create({
                        'move_type': 'out_invoice',
                        'partner_id': self.partner_a.id,
                        'journal_id': self.journal_sale.id,
                        'invoice_date': '2026-01-01',
                        'date': '2026-01-01',
                        'invoice_line_ids': [Command.create({
                            'name': 'Continuing revenue',
                            'account_id': self.account_revenue.id,
                            'quantity': 1.0,
                            'price_unit': 100.0,
                            'tax_ids': [Command.clear()],
                        })],
                    })
                    ordinary.action_post()
                    self.assertEqual(ordinary.copy().state, 'draft')
                    wizard = self._acting(
                        self.env['account.move.reversal'], user,
                    ).with_context(
                        active_model='account.move',
                        active_ids=ordinary.ids,
                    ).create({
                        'date': '2026-01-01',
                        'journal_id': ordinary.journal_id.id,
                    })
                    wizard.modify_moves()
                    self.assertEqual(len(wizard.new_move_ids), 1)
                    self.assertEqual(wizard.new_move_ids.state, 'draft')
                    self.assertEqual(
                        ordinary.reversal_move_ids.state, 'posted')
                    self.assertFalse(
                        (wizard.new_move_ids | ordinary.reversal_move_ids)
                        .line_ids._eh_discontinued_scoped_lines())

    # ---- the Reverse wizard as the web client drives it ----

    def _rpc_actors(self):
        """Every role that can click Reverse, and whether it reads evidence.

        Only the superuser and the EH Accounting Manager may seal a
        discontinued scope. The EH Accounting User reads the evidence but
        may not seal; the core accountant and the billing user, who have no
        EH group, may not even read it.
        """
        actors = (
            ('superuser', False, True),
            ('eh_manager', self.eh_manager, True),
            ('eh_user', self.eh_user, True),
            ('core_accountant', self.core_account_manager, False),
            ('billing', self.billing_user, False),
        )
        for _label, user, reads in actors:
            if not user:
                continue
            self.assertEqual(
                user.has_group('eh_account_base.group_eh_manager'),
                user == self.eh_manager,
            )
            for model_name in ('eh.held.for.sale', 'eh.disposal.group'):
                self.assertEqual(
                    self.env[model_name].with_user(user).has_access('read'),
                    reads,
                )
        return actors

    def _rpc(self, user, model, method, args, context=None):
        """Call ``method`` the way the web client's call_kw and call_button do.

        Arguments and context travel as JSON, so a caller can send nothing
        but plain values, and call_kw puts that context on the records.
        """
        payload = json.loads(json.dumps({
            'args': args,
            'context': dict(
                context or {}, allowed_company_ids=self.company.ids),
        }))
        env = self.env(user=user) if user else self.env
        return call_kw(
            env[model], method, payload['args'],
            {'context': payload['context']},
        )

    def _reverse_over_rpc(self, user, source, context=None):
        """Open the Reverse wizard on ``source`` and click Reverse."""
        wizard_context = {
            'active_model': 'account.move', 'active_ids': source.ids,
        }
        wizard_id = self._rpc(user, 'account.move.reversal', 'create', [{
            'reason': 'Discontinued scope probe',
            'date': '2026-01-01',
            'journal_id': source.journal_id.id,
        }], wizard_context)
        self._rpc(
            user, 'account.move.reversal', 'refund_moves', [[wizard_id]],
            dict(wizard_context, **(context or {})),
        )
        return self.env['account.move.reversal'].browse(
            wizard_id).new_move_ids

    def _evidence_rows(self):
        """Every discontinued-operation link, straight from the tables."""
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT 'hfs', line_id, item_id
              FROM eh_hfs_disc_evidence_move_line_rel
            UNION ALL
            SELECT 'group', line_id, group_id
              FROM eh_dg_disc_evidence_move_line_rel
        """)
        return set(self.env.cr.fetchall())

    def _sealed_operation(self):
        """A sealed item and a sealed group, each owning one posted item."""
        scoped = self._scoped_move(
            'entry').line_ids._eh_discontinued_scoped_lines().sudo()
        return (
            scoped.eh_discontinued_hfs_ids,
            scoped.eh_discontinued_group_ids,
            scoped,
        )

    def test_reversal_wizard_over_rpc_carries_the_source_scope(self):
        """Every role's Reverse click keeps the discontinued result whole.

        The counter entry takes each scoped item's exact scope whoever
        clicks, so posting it nets the discontinued result back to what it
        was before the source.
        """
        for label, user, _reads in self._rpc_actors():
            for move_type in ('entry', 'out_invoice'):
                with self.subTest(actor=label, move_type=move_type):
                    before = self._discontinued_total()
                    source = self._scoped_move(move_type)
                    counter = self._reverse_over_rpc(user, source)
                    self.assertEqual(len(counter), 1)
                    self.assertEqual(counter.reversed_entry_id, source)
                    self._assert_counter_scope(source, counter)
                    if counter.state == 'draft':
                        self._rpc(
                            user, 'account.move', 'action_post',
                            [counter.ids])
                    self.assertEqual(counter.state, 'posted')
                    self._assert_counter_scope(source, counter)
                    self.assertAlmostEqual(
                        self._discontinued_total(), before)

    def test_reversal_over_rpc_refuses_scope_from_context_defaults(self):
        """A crafted Reverse click cannot add an item to a sealed operation.

        Core fills the counter entry's invoice lines from the caller's
        default_invoice_line_ids. A line there naming a sealed operation's
        evidence would join that operation without Seal Discontinued Scope,
        which only a manager may run. Whoever clicks, the counter entry
        carries nothing but the scope of the items it reverses: a caller
        who may read the evidence is refused and nothing is written, and
        for one who may not, core drops the ids it cannot read.
        """
        item, group, sealed = self._sealed_operation()
        sealed_owners = {('hfs', item.id), ('group', group.id)}
        forged = [Command.create({
            'name': 'Forged discontinued line',
            'account_id': self.account_revenue.id,
            'quantity': 1.0,
            'price_unit': 777.0,
            'tax_ids': [Command.clear()],
            'eh_discontinued_hfs_ids': [Command.set(item.ids)],
            'eh_discontinued_group_ids': [Command.set(group.ids)],
        })]
        Move = self.env['account.move']
        for label, user, reads in self._rpc_actors():
            for source_kind in (
                    'ordinary_invoice', 'scoped_entry', 'scoped_invoice'):
                with self.subTest(actor=label, source=source_kind):
                    total = self._discontinued_total()
                    if source_kind == 'ordinary_invoice':
                        source = Move.create({
                            'move_type': 'out_invoice',
                            'partner_id': self.partner_a.id,
                            'journal_id': self.journal_sale.id,
                            'invoice_date': '2026-01-01',
                            'date': '2026-01-01',
                            'invoice_line_ids': [Command.create({
                                'name': 'Continuing revenue',
                                'account_id': self.account_revenue.id,
                                'quantity': 1.0,
                                'price_unit': 100.0,
                                'tax_ids': [Command.clear()],
                            })],
                        })
                        source.action_post()
                    else:
                        source = self._scoped_move(
                            'entry' if source_kind == 'scoped_entry'
                            else 'out_invoice')
                    rows = self._evidence_rows()
                    count = Move.search_count([])
                    context = {'default_invoice_line_ids': forged}
                    if reads:
                        with self.assertRaisesRegex(
                                AccessError, 'carries only the scope'), \
                                self.env.cr.savepoint():
                            self._reverse_over_rpc(user, source, context)
                        self.env.invalidate_all()
                        self.assertEqual(Move.search_count([]), count)
                        self.assertFalse(source.reversal_move_ids)
                        self.assertEqual(self._evidence_rows(), rows)
                        continue
                    counter = self._reverse_over_rpc(user, source, context)
                    self.assertEqual(len(counter), 1)
                    if source_kind == 'ordinary_invoice':
                        self.assertFalse(
                            counter.line_ids._eh_discontinued_scoped_lines())
                    else:
                        self._assert_counter_scope(source, counter)
                    if counter.state == 'draft':
                        counter.action_post()
                    self.assertAlmostEqual(
                        self._discontinued_total(), total)
                    self.assertEqual(
                        {row for row in self._evidence_rows()
                         if (row[0], row[2]) in sealed_owners},
                        {row for row in rows
                         if (row[0], row[2]) in sealed_owners},
                    )
        self.assertEqual(
            sealed._eh_discontinued_scoped_lines(), sealed)

    def _inside_reversal(self, action):
        """Run ``action(new_moves, source)`` from inside a real reversal.

        Mail logs the counter entry's creation from inside
        account.move.create, while core is still building that entry, so
        ``action`` runs with the very context the reversal gives its own
        writes, as a hook there would.
        """
        Move = type(self.env['account.move'])
        log_batch = Move._message_log_batch
        ran = []

        def hook(moves, *args, **kwargs):
            if not ran and moves.reversed_entry_id:
                ran.append(moves.env.context.get(
                    'eh_discontinued_line_capability'))
                action(moves, moves.reversed_entry_id)
            return log_batch(moves, *args, **kwargs)

        return patch.object(Move, '_message_log_batch', hook), ran

    def test_reversal_capability_writes_only_its_own_counter_items(self):
        """Inside a reversal only the counter items it creates take scope.

        A hook running inside _reverse_moves may neither clear a posted
        item's scope, nor give an ordinary posted item one, nor edit the
        scoped draft items of another reversal, nor hand one copied scope
        to two new items.
        """
        _item, _group, sealed = self._sealed_operation()
        sealed_line = sealed.filtered('eh_discontinued_hfs_ids')
        sealed_item = sealed_line.eh_discontinued_hfs_ids
        ordinary = self.post_balanced_move([
            {'account': self.account_expense, 'debit': 15.0},
            {'account': self.account_cash, 'credit': 15.0},
        ], date='2026-01-01')
        ordinary_line = ordinary.line_ids.filtered(
            lambda line: line.account_id == self.account_expense)
        pending = self._scoped_move('entry')._reverse_moves(cancel=False)
        self.assertEqual(pending.state, 'draft')
        pending_line = pending.line_ids._eh_discontinued_scoped_lines()[:1]
        pending_account = pending_line.account_id

        def clear_posted_scope(moves, source):
            moves.env['account.move.line'].browse(sealed_line.id).write({
                'eh_discontinued_hfs_ids': [Command.clear()],
            })

        def scope_ordinary_item(moves, source):
            moves.env['account.move.line'].browse(ordinary_line.id).write({
                'eh_discontinued_hfs_ids': [Command.set(sealed_item.ids)],
            })

        def edit_other_reversal(moves, source):
            moves.env['account.move.line'].browse(pending_line.id).write({
                'account_id': self.account_expense.id,
            })

        def copy_scope_twice(moves, source):
            Line = moves.env['account.move.line'].with_context(
                check_move_validity=False)
            scoped = source.line_ids._eh_discontinued_scoped_lines()[:1]
            vals = Line.browse(scoped.id).copy_data()[0]
            for _copy in range(2):
                Line.create(dict(
                    vals, move_id=moves.id, balance=0.0,
                    amount_currency=0.0))

        attempts = (
            ('clear_posted_scope', clear_posted_scope,
             AccessError, 'immutable'),
            ('scope_ordinary_item', scope_ordinary_item,
             AccessError, 'immutable'),
            ('edit_other_reversal', edit_other_reversal,
             UserError, 'frozen discontinued-operation'),
            ('copy_scope_twice', copy_scope_twice,
             AccessError, 'carries only the scope'),
        )
        for label, user in (('superuser', False), ('eh_user', self.eh_user)):
            for name, action, error, message in attempts:
                with self.subTest(actor=label, attempt=name):
                    source = self._scoped_move('entry')
                    rows = self._evidence_rows()
                    patcher, ran = self._inside_reversal(action)
                    with patcher, self.assertRaisesRegex(error, message), \
                            self.env.cr.savepoint():
                        self._acting(source, user)._reverse_moves(
                            cancel=True)
                    self.assertTrue(ran and ran[0])
                    self.env.invalidate_all()
                    self.assertFalse(source.reversal_move_ids)
                    self.assertEqual(self._evidence_rows(), rows)
                    self.assertEqual(pending_line.account_id, pending_account)
        self.assertEqual(
            sealed_line._eh_discontinued_scoped_lines(), sealed_line)

    def test_foreign_journal_is_rejected_before_action(self):
        foreign = self.env['res.company'].create({'name': 'HFS Foreign Co'})
        foreign_journal = self.env['account.journal'].create({
            'name': 'HFS Foreign Miscellaneous',
            'code': 'HFX',
            'type': 'general',
            'company_id': foreign.id,
        })
        item = self._item()
        with self.assertRaises(ValidationError):
            item.write({'journal_id': foreign_journal.id})

    def test_actions_take_row_locks(self):
        item = self._item()
        seen = []
        real_execute = self.env.cr.execute

        def _record_execute(*args, **kwargs):
            if args:
                seen.append(str(args[0]))
            return real_execute(*args, **kwargs)

        with patch.object(self.env.cr, 'execute', _record_execute):
            item.action_classify()
        self.assertTrue(any(
            'eh_held_for_sale' in query and 'FOR UPDATE' in query
            for query in seen
        ))

    def test_member_create_rechecks_group_state_after_lock(self):
        group = self._group()
        line = group.line_ids
        line.unlink()
        model_class = group.__class__
        real_lock = model_class._eh_lock_for_transition

        def _classify_while_waiting(records):
            result = real_lock(records)
            if group.id in records.ids:
                self.env.cr.execute(
                    "UPDATE eh_disposal_group SET state = 'held' "
                    "WHERE id = %s", (group.id,))
                records.invalidate_recordset(['state'])
            return result

        with self.assertRaises(UserError):
            with self.env.cr.savepoint(), patch.object(
                    model_class, '_eh_lock_for_transition',
                    _classify_while_waiting):
                self.env['eh.disposal.group.line'].create({
                    'group_id': group.id,
                    'name': 'Concurrent late member',
                    'carrying_amount': 1.0,
                    'account_id': self.asset.id,
                })
