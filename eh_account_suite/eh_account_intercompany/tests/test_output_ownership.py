# Copyright (C) 2026 ERP Heritage.
"""Optional cross-module accounting-output ownership acceptance tests.

Run with both eh_account_intercompany and eh_account_consolidation installed.
The real posting fixture reproduces a 100-unit IC trade and 30-unit external
receipt. Each engine can operate independently; their outputs cannot share a
company because the consolidation snapshot already contains its eliminations.
"""
from uuid import uuid4

from psycopg2.errors import SerializationFailure

from odoo import api, SUPERUSER_ID
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

from .test_golden_ic_elimination import TestGoldenIcElimination


def _unlink_each(env, records):
    """Unlink ``records`` in one batch, else one by one, skipping refusals."""
    try:
        with env.cr.savepoint():
            records.unlink()
        return
    except Exception:  # noqa: BLE001
        pass
    for record in records:
        try:
            with env.cr.savepoint():
                record.unlink()
        except Exception:  # noqa: BLE001
            continue


def _purge_committed_companies(env, company_ids):
    """Delete committed fixture companies with the records seeded for them.

    Installed modules seed records for every new company (payment providers,
    warehouses with their operation types and locations, tax returns, setup
    checklist rows), several behind RESTRICT foreign keys, so a plain
    ``unlink()`` of the companies fails once enough modules are installed and
    the committed fixture would leak into every later test and run. Each
    stored many2one to ``res.company`` is walked and its records for these
    companies are removed through the ORM, repeating until the companies go.
    Records that a company row itself still pinned (its working calendar or
    transit location) and the company contacts are removed once the company
    is gone, so none is left behind without a company. Archived records count too: an unlink that
    searches its own records (stock locations unlink their children) would
    otherwise skip them.
    """
    env = env(context=dict(env.context, active_test=False))
    partners = env['res.company'].browse(company_ids).exists().partner_id
    company_fields = [
        (model_name, field.name)
        for model_name, model in env.registry.items()
        if not model._abstract and model._auto and not model._transient
        and model_name != 'res.company'
        for field in model._fields.values()
        if field.type == 'many2one' and field.store
        and field.comodel_name == 'res.company'
    ]
    seeded = {}
    for _attempt in range(5):
        companies = env['res.company'].browse(company_ids).exists()
        if not companies:
            break
        try:
            with env.cr.savepoint():
                companies.unlink()
            break
        except Exception:  # noqa: BLE001
            pass
        for model_name, field_name in company_fields:
            try:
                with env.cr.savepoint():
                    records = env[model_name].search(
                        [(field_name, 'in', companies.ids)])
            except Exception:  # noqa: BLE001
                continue
            if records:
                seeded.setdefault(model_name, set()).update(records.ids)
                _unlink_each(env, records)
    for _attempt in range(3):
        left = [
            records for records in (
                env[model_name].browse(record_ids).exists()
                for model_name, record_ids in seeded.items()
            ) if records
        ]
        if not left:
            break
        for records in left:
            _unlink_each(env, records)
    companies = env['res.company'].browse(company_ids).exists()
    if not companies and partners.exists():
        # Deleting a company keeps its contact; the fixture's go as well.
        _unlink_each(env, partners.exists())
    if companies:
        raise AssertionError(
            'Committed fixture companies could not be removed: %s'
            % companies.ids)


@tagged('eh_output_ownership', 'post_install', '-at_install')
class TestGroupOutputOwnership(TestGoldenIcElimination):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'eh.consol.entity' not in cls.env:
            from unittest import SkipTest
            raise SkipTest('Optional Group Consolidation integration not installed')

    def setUp(self):
        super().setUp()
        self.output = self.env['res.company'].create({
            'name': 'Full consolidated output',
            'currency_id': self.company_a.currency_id.id,
        })
        self.env.user.company_ids |= self.output
        companies = self.company_a | self.company_b | self.company_elim | self.output
        self.env = self.env(context=dict(self.env.context, allowed_company_ids=companies.ids))
        self.Move = self.env['account.move']
        self.Batch = self.env['eh.ic.elimination.batch']
        Account = self.env['account.account'].with_company(self.output)
        for source in (self.account_cash | self.account_receivable |
                       self.account_payable | self.account_revenue | self.account_expense):
            Account.create({
                'name': source.name,
                'code': source.with_company(self.company_a).code,
                'account_type': source.account_type,
                'reconcile': source.reconcile,
                'company_ids': [(6, 0, self.output.ids)],
            })
        self.output_journal = self.env['account.journal'].create({
            'name': 'Full consolidation', 'code': 'FULL', 'type': 'general',
            'company_id': self.output.id,
        })

    def _entity_vals(self, output=None):
        return {
            'name': 'Output ownership group', 'code': 'output_' + uuid4().hex[:12],
            'parent_company_id': self.company_a.id,
            'presentation_currency_id': self.company_a.currency_id.id,
            'consolidation_company_id': output.id if output else False,
            'auto_eliminate_investment': False,
            'auto_eliminate_intragroup': True,
            'member_ids': [(0, 0, {
                'company_id': self.company_b.id, 'ownership_pct': 100, 'method': 'full',
            })],
        }

    def _post_source_trade(self):
        self.company_a.partner_id.eh_represented_company_id = self.company_a
        self.company_b.partner_id.eh_represented_company_id = self.company_b
        self.company_b.partner_id.with_company(self.company_a).property_account_receivable_id = self.account_receivable
        invoice = self._make_sale_invoice(price=100, partner=self.company_b.partner_id)
        invoice.action_post()
        self.assertEqual(invoice.eh_intercompany_mirror_id.state, 'posted')
        self.post_balanced_move([
            {'account': self.account_cash, 'debit': 30},
            {'account': self.account_revenue, 'credit': 30},
        ], date='2026-03-15')
        return invoice

    def _computed_run(self, entity):
        run = self.env['eh.consol.run'].create({
            'entity_id': entity.id, 'period_from': '2026-03-01', 'period_to': '2026-03-31',
        })
        run.action_compute()
        return run

    def _computed_batch(self):
        batch = self._make_batch()
        batch.action_compute()
        self._approve_unrealised(batch, fraction=0)
        return batch

    def _posted_balances(self, company):
        balances = {}
        for line in self.env['account.move.line'].search([
            ('company_id', '=', company.id), ('parent_state', '=', 'posted'),
        ]):
            code = line.account_id.with_company(company).code
            balances[code] = round(balances.get(code, 0) + line.balance, 2)
        return {code: value for code, value in balances.items() if value}

    def _legacy_bind(self, entity, output):
        # Emulate a database configured before the new ownership guard. No
        # financial figure/state is forged: compute/post still use real ORM.
        entity.flush_recordset()
        self.env.cr.execute(
            'UPDATE eh_consol_entity SET consolidation_company_id = %s WHERE id = %s',
            (output.id, entity.id),
        )
        entity.invalidate_recordset()
        entity._eh_invalidate_company_scope_cache()

    def test_consolidation_assignment_rejects_ic_output_in_both_entry_paths(self):
        with self.assertRaisesRegex(ValidationError, 'IC elimination output'):
            self.env['eh.consol.entity'].create(self._entity_vals(self.company_elim))
        entity = self.env['eh.consol.entity'].create(self._entity_vals())
        with self.assertRaisesRegex(ValidationError, 'IC elimination output'):
            entity.write({'consolidation_company_id': self.company_elim.id})
        vals = self._entity_vals()
        vals.pop('consolidation_company_id')
        with self.assertRaisesRegex(ValidationError, 'IC elimination output'):
            self.env['eh.consol.entity'].with_context(
                default_consolidation_company_id=self.company_elim.id,
            ).create(vals)

    def test_ic_role_enable_rejects_existing_full_consolidation_output(self):
        self.env['eh.consol.entity'].create(self._entity_vals(self.output))
        with self.assertRaisesRegex(UserError, 'reserved for full Group Consolidation'), self.env.cr.savepoint():
            self.output.eh_ic_consolidation_only = True
        self.assertFalse(self.output.eh_ic_consolidation_only)

    def test_posted_ic_history_cannot_be_released_by_false_like_values(self):
        self._post_source_trade()
        batch = self._computed_batch()
        batch.action_post()
        for value in (False, 0, None, ''):
            with self.subTest(value=value):
                with self.assertRaisesRegex(UserError, 'cannot be converted'), self.env.cr.savepoint():
                    self.company_elim.write({'eh_ic_consolidation_only': value})
                self.assertTrue(self.company_elim.eh_ic_consolidation_only)
        # Historic databases may already have a false role flag. The actual
        # immutable journal history still reserves their output company.
        self.company_elim.flush_recordset(['eh_ic_consolidation_only'])
        self.env.cr.execute(
            'UPDATE res_company SET eh_ic_consolidation_only = FALSE WHERE id = %s',
            (self.company_elim.id,),
        )
        self.company_elim.invalidate_recordset(['eh_ic_consolidation_only'])
        with self.assertRaisesRegex(ValidationError, 'IC elimination output'):
            self.env['eh.consol.entity'].create(self._entity_vals(self.company_elim))

    def test_output_roles_cannot_overlap_root_or_sibling_branches(self):
        branches = self.env['res.company'].create([
            {'name': 'Full output branch one', 'parent_id': self.output.id},
            {'name': 'Full output branch two', 'parent_id': self.output.id},
        ])
        self.env.user.company_ids |= branches
        self.env = self.env(context=dict(
            self.env.context, allowed_company_ids=self.env.companies.ids + branches.ids,
        ))
        self.env['eh.consol.entity'].create(self._entity_vals(branches[0]))
        for company in self.output | branches:
            with self.subTest(company=company.name):
                with self.assertRaisesRegex(UserError, 'legal-company root'), self.env.cr.savepoint():
                    company.write({'eh_ic_consolidation_only': True})
        with self.assertRaisesRegex(UserError, 'legal-company root'), self.env.cr.savepoint():
            self.env['res.company'].create({
                'name': 'Cannot create conflicting output branch',
                'parent_id': self.output.id, 'eh_ic_consolidation_only': True,
            })
        ic_branch = self.env['res.company'].create({
            'name': 'IC output branch', 'parent_id': self.company_elim.id,
        })
        self.env.user.company_ids |= ic_branch
        self.env = self.env(context=dict(
            self.env.context, allowed_company_ids=self.env.companies.ids + ic_branch.ids,
        ))
        with self.assertRaisesRegex(ValidationError, 'legal-company root'):
            self.env['eh.consol.entity'].create(self._entity_vals(ic_branch))
        # Odoo 20 rejects reparenting existing companies at the ORM boundary.
        with self.assertRaises(UserError), self.env.cr.savepoint():
            ic_branch.write({'parent_id': self.output.id})

    def test_separate_companies_keep_both_real_outputs_correct(self):
        self._post_source_trade()
        entity = self.env['eh.consol.entity'].create(self._entity_vals(self.output))
        run = self._computed_run(entity)
        run.action_post_move()
        self.assertEqual(self._posted_balances(self.output), {'1000': 30.0, '4000': -30.0})
        batch = self._computed_batch()
        batch.action_post()
        self.assertEqual(self._posted_balances(self.output), {'1000': 30.0, '4000': -30.0})
        self.assertEqual(self._posted_balances(self.company_elim), {
            '1100': -100.0, '2100': 100.0, '4000': 100.0, '5000': -100.0,
        })

    def test_memo_only_consolidation_does_not_reserve_ic_output(self):
        self._post_source_trade()
        entity = self.env['eh.consol.entity'].create(self._entity_vals())
        run = self._computed_run(entity)
        batch = self._computed_batch()
        batch.action_post()
        self.assertEqual(run.state, 'computed')
        self.assertFalse(run.move_id)
        self.assertEqual(batch.state, 'posted')

    def test_legacy_shared_target_blocks_new_config_batch_and_both_posts(self):
        self._post_source_trade()
        batch = self._computed_batch()
        entity = self.env['eh.consol.entity'].create(self._entity_vals())
        self._legacy_bind(entity, self.company_elim)
        # Add the external-cash code used by the full snapshot.
        self.env['account.account'].with_company(self.company_elim).create({
            'name': 'Legacy output cash', 'code': '1000', 'account_type': 'asset_cash',
            'company_ids': [(6, 0, self.company_elim.ids)],
        })
        run = self._computed_run(entity)
        with self.assertRaisesRegex(ValidationError, 'IC elimination output'):
            run.action_post_move()
        with self.assertRaisesRegex(UserError, 'reserved for full Group Consolidation'):
            batch.action_post()
        with self.assertRaisesRegex(UserError, 'reserved for full Group Consolidation'), self.env.cr.savepoint():
            self.config_a.write({'elimination_company_id': self.company_elim.id})
        with self.assertRaisesRegex(UserError, 'reserved for full Group Consolidation'), self.env.cr.savepoint():
            self._make_batch(period_from='2026-04-01', period_to='2026-04-30')
        self.assertFalse(run.move_id)
        self.assertFalse(batch.move_id)
        self.assertEqual(self._posted_balances(self.company_elim), {})

    def test_legacy_ic_output_can_still_reverse_after_conflict_is_detected(self):
        self._post_source_trade()
        batch = self._computed_batch()
        batch.action_post()
        entity = self.env['eh.consol.entity'].create(self._entity_vals())
        self._legacy_bind(entity, self.company_elim)
        batch.action_reset_to_draft()
        self.assertEqual(batch.state, 'draft')
        self.assertTrue(batch.reversal_move_id)
        self.assertEqual(self._posted_balances(self.company_elim), {})

    def test_legacy_consolidation_output_can_still_reverse(self):
        self._post_source_trade()
        entity = self.env['eh.consol.entity'].create(self._entity_vals(self.output))
        run = self._computed_run(entity)
        run.action_post_move()
        self.output.flush_recordset(['eh_ic_consolidation_only'])
        self.env.cr.execute('UPDATE res_company SET eh_ic_consolidation_only = TRUE WHERE id = %s', (self.output.id,))
        self.output.invalidate_recordset(['eh_ic_consolidation_only'])
        run.action_reset_to_draft()
        self.assertEqual(run.state, 'draft')
        self.assertTrue(run.reversal_move_id)
        self.assertEqual(self._posted_balances(self.output), {})



@tagged('eh_output_ownership', 'post_install', '-at_install')
class TestGroupOutputConcurrency(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'eh.consol.entity' not in cls.env:
            from unittest import SkipTest
            raise SkipTest('Optional Group Consolidation integration not installed')

    @mute_logger('odoo.sql_db')
    def test_concurrent_role_and_entity_assignment_retry_in_both_orders(self):
        # Independent committed fixtures are required to test real PostgreSQL
        # snapshots; keep them outside the shared TransactionCase fixture and
        # remove every row in finally. No business journal entries are made.
        registry = self.env.registry
        created_ids = []
        try:
            with registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                companies = env['res.company'].create([
                    {'name': 'Concurrent ownership parent ' + uuid4().hex[:8]},
                    {'name': 'Concurrent ownership output ' + uuid4().hex[:8]},
                ])
                created_ids = companies.ids
                branches = env['res.company'].create([
                    {'name': 'Concurrent full output branch ' + uuid4().hex[:8], 'parent_id': companies[1].id},
                    {'name': 'Concurrent IC output branch ' + uuid4().hex[:8], 'parent_id': companies[1].id},
                ])
                created_ids += branches.ids
                cr.commit()
            for ic_first, use_branches in ((False, False), (True, False), (False, True), (True, True)):
                consolidation_id = created_ids[2] if use_branches else created_ids[1]
                ic_id = created_ids[3] if use_branches else created_ids[1]
                with registry.cursor() as clean_cr:
                    clean_env = api.Environment(clean_cr, SUPERUSER_ID, {})
                    clean_env['eh.consol.entity'].search([('consolidation_company_id', 'in', created_ids)]).unlink()
                    clean_env['res.company'].browse(created_ids[1:]).write({'eh_ic_consolidation_only': False})
                    clean_cr.commit()
                with registry.cursor() as consol_cr, registry.cursor() as ic_cr:
                    consol_env = api.Environment(consol_cr, SUPERUSER_ID, {})
                    ic_env = api.Environment(ic_cr, SUPERUSER_ID, {})
                    vals = {
                        'name': 'Concurrent output reservation', 'code': 'race_' + uuid4().hex[:12],
                        'parent_company_id': created_ids[0], 'consolidation_company_id': consolidation_id,
                    }
                    # Pin both snapshots before the winner commits.
                    for env in (consol_env, ic_env):
                        self.assertFalse(env['res.company'].browse(ic_id).eh_ic_consolidation_only)
                    if ic_first:
                        ic_env['res.company'].browse(ic_id).write({'eh_ic_consolidation_only': True})
                        ic_cr.commit()
                        with self.assertRaises(SerializationFailure):
                            consol_env['eh.consol.entity'].create(vals)
                        consol_cr.rollback()
                    else:
                        consol_env['eh.consol.entity'].create(vals)
                        consol_cr.commit()
                        with self.assertRaises(SerializationFailure):
                            ic_env['res.company'].browse(ic_id).write({'eh_ic_consolidation_only': True})
                        ic_cr.rollback()
                # A fresh request sees the committed owner and gets the
                # business error, rather than two successful assignments.
                with registry.cursor() as retry_cr:
                    retry_env = api.Environment(retry_cr, SUPERUSER_ID, {})
                    with self.assertRaises((UserError, ValidationError)):
                        if ic_first:
                            retry_env['eh.consol.entity'].create(vals)
                        else:
                            retry_env['res.company'].browse(ic_id).write({'eh_ic_consolidation_only': True})
                    retry_cr.rollback()
        finally:
            if created_ids:
                with registry.cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    env['eh.consol.entity'].search([('consolidation_company_id', 'in', created_ids)]).unlink()
                    _purge_committed_companies(env, created_ids)
                    cr.commit()
