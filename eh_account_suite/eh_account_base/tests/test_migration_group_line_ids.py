# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""The 20.0.1.8.0 upgrade retires line ids built from Odoo 19 account groups.

On 19 a hierarchy row id ``section-<section>-group-<ids>`` carried
account.group ids; on 20 the same shape carries parent account ids. A note
left on a 19 group row must never land on whichever 20 row now has the same
id, and must follow its row when the group became a parent account.
"""

import importlib.util
from pathlib import Path

from odoo.tests import tagged

from .common import EhAccountUnitTestCase


def _load_migration():
    path = (
        Path(__file__).parents[1]
        / 'migrations' / '20.0.1.8.0' / 'post-migration.py'
    )
    spec = importlib.util.spec_from_file_location(
        'eh_account_base_post_migration_20_0_1_8_0', path,
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


@tagged('eh_account_base', 'post_install', '-at_install')
class TestGroupLineIdMigration(EhAccountUnitTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Group line id migration company',
        })
        Account = cls.env['account.account'].with_company(cls.company)
        common = {'company_ids': [(6, 0, cls.company.ids)]}
        # The upgrade turns each account group into an (inactive) parent
        # account that carries the group's code prefix.
        cls.assets = Account.create(dict(
            common, name='Assets', code='EHM1',
            account_type='asset_current', active=False,
        ))
        cls.current = Account.create(dict(
            common, name='Current assets', code='EHM11',
            account_type='asset_current', parent_id=cls.assets.id,
            active=False,
        ))
        cls.bank = Account.create(dict(
            common, name='Bank', code='EHM110001',
            account_type='asset_cash', parent_id=cls.current.id,
        ))
        cls.report = cls.env['eh.account.dynamic.report'].create({
            'code': 'eh_group_line_migration',
            'name': 'Group line migration report',
            'handler_model': 'eh.account.dynamic.report.handler',
        })
        cls.new_current_id = 'section-assets-group-%s_%s' % (
            cls.assets.id, cls.current.id,
        )

    def _note(self, line_id, label=False):
        return self.env['eh.account.report.annotation'].create({
            'report_code': self.report.code,
            'line_id': line_id,
            'expression_label': label,
            'text': 'Auditor note on %s' % line_id,
            'company_id': self.company.id,
        })

    def _legacy_group_table(self, groups):
        """Recreate the account_group rows the 19 database still holds."""
        self.env.cr.execute("SELECT to_regclass('account_group')")
        self.assertIsNone(self.env.cr.fetchone()[0])
        self.env.cr.execute("""
            CREATE TABLE account_group (
                id integer PRIMARY KEY,
                %s varchar,
                %s varchar,
                company_id integer
            )
        """ % (_load_migration().PREFIX_START, _load_migration().PREFIX_END))
        for group_id, start, end in groups:
            self.env.cr.execute(
                "INSERT INTO account_group VALUES (%s, %s, %s, %s)",
                (group_id, start, end, self.company.id),
            )

    def _migrate(self, version='19.0.1.7.20'):
        self.env.flush_all()
        _load_migration().migrate(self.env.cr, version)
        self.env.invalidate_all()

    def _render(self, line_ids):
        payload = {'lines': [
            {'id': line_id, 'columns': [{'expression_label': 'balance'}]}
            for line_id in line_ids
        ]}
        return self.report._eh_apply_annotations(payload, self.company.ids)

    def test_colliding_group_note_is_detached_not_misattached(self):
        """Without the legacy table no mapping is provable: a 19 group row
        id that equals a 20 parent account row id must not show its note
        on that unrelated row, and the note itself is kept."""
        # 19 group ids that happen to equal the 20 parent account ids.
        stale = self._note(self.new_current_id)
        stale_cell = self._note(self.new_current_id, 'balance')
        account_note = self._note('account-%s' % self.bank.id)
        header_note = self._note('section-assets-header')
        self._migrate()

        migration = _load_migration()
        self.assertEqual(
            stale.line_id, migration.DETACHED_PREFIX + self.new_current_id,
        )
        self.assertEqual(
            stale_cell.line_id,
            migration.DETACHED_PREFIX + self.new_current_id,
        )
        self.assertEqual(stale.text, 'Auditor note on %s' % self.new_current_id)
        self.assertEqual(account_note.line_id, 'account-%s' % self.bank.id)
        self.assertEqual(header_note.line_id, 'section-assets-header')

        lines = {
            line['id']: line for line in self._render([
                self.new_current_id,
                'account-%s' % self.bank.id,
                'section-assets-header',
            ])['lines']
        }
        current = lines[self.new_current_id]
        self.assertNotIn('annotations', current.get('meta', {}))
        self.assertNotIn('annotations', current['columns'][0])
        self.assertEqual(
            [note['id'] for note in lines['account-%s' % self.bank.id]
             ['meta']['annotations']],
            account_note.ids,
        )
        self.assertEqual(
            [note['id'] for note in lines['section-assets-header']
             ['meta']['annotations']],
            header_note.ids,
        )

    def test_group_note_follows_its_parent_account(self):
        """A group whose code prefix names exactly one parent account moves
        its note to that account's row; an ambiguous group is detached."""
        self._legacy_group_table([
            (901, 'EHM1', 'EHM1'),
            (902, 'EHM11', 'EHM11'),
            # A range cannot name a single parent account.
            (903, 'EHM11', 'EHM19'),
            # No parent account carries this code.
            (904, 'EHM7', 'EHM7'),
        ])
        followed = self._note('section-assets-group-901_902', 'balance')
        root = self._note('section-assets-group-901')
        ranged = self._note('section-assets-group-901_903')
        unknown = self._note('section-assets-group-904')
        self._migrate()

        migration = _load_migration()
        self.assertEqual(followed.line_id, self.new_current_id)
        self.assertEqual(followed.expression_label, 'balance')
        self.assertEqual(
            root.line_id, 'section-assets-group-%s' % self.assets.id,
        )
        self.assertEqual(
            ranged.line_id,
            migration.DETACHED_PREFIX + 'section-assets-group-901_903',
        )
        self.assertEqual(
            unknown.line_id,
            migration.DETACHED_PREFIX + 'section-assets-group-904',
        )
        current = self._render([self.new_current_id])['lines'][0]
        self.assertEqual(
            [note['id'] for note in current['columns'][0]['annotations']],
            followed.ids,
        )

    def test_group_fold_states_are_reset(self):
        FoldState = self.env['eh.account.report.fold.state']
        group_state = FoldState.set_for_user(
            self.report.code, 'section-assets-group-12_47', False,
        )
        other_state = FoldState.set_for_user(
            self.report.code, 'account-%s' % self.bank.id, False,
        )
        self._migrate()
        self.assertFalse(group_state.exists())
        self.assertTrue(other_state.exists())

    def test_runs_only_when_upgrading_from_19(self):
        stale = self._note(self.new_current_id)
        state = self.env['eh.account.report.fold.state'].set_for_user(
            self.report.code, self.new_current_id, False,
        )
        # A fresh install and a 20 to 20 upgrade keep 20 line ids as is.
        self._migrate(version=False)
        self._migrate(version='20.0.1.7.9')
        self.assertEqual(stale.line_id, self.new_current_id)
        self.assertTrue(state.exists())
