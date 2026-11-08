# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Unit tests for MoveLineQuery: shape and parameter binding.

These tests do NOT execute the composed SQL. They only inspect the rendered
code and params, which is enough to verify:

* The mandatory company filter is always emitted.
* The mandatory cancel exclusion is always emitted.
* User supplied data only lands in params, never in the SQL string.
* Whitelists reject unknown identifiers.
* Composition (joins, group_by, order_by, limit, offset) renders correctly.
"""

from odoo.release import version_info
from odoo.exceptions import UserError
from odoo.tools import SQL
from odoo.tests import tagged

from odoo.addons.eh_account_base.tools.sql_builder import (
    MoveLineQuery, MoveLineQueryError, sql_code, sql_params,
)
from .common import EhAccountUnitTestCase


@tagged('eh_account_base', 'unit')
class TestMoveLineQueryShape(EhAccountUnitTestCase):

    def setUp(self):
        super().setUp()
        self.cid = self.env.company.id

    def _q(self):
        return MoveLineQuery(self.env, company_ids=[self.cid])

    def _assert_account_code_expression(self, sql):
        if version_info[0] >= 18:
            self.assertIn('JOIN res_company aml_company', sql_code(sql))
            self.assertIn('acc.code_store', sql_code(sql))
            self.assertIn('aml_company.parent_path', sql_code(sql))
        else:
            self.assertNotIn('JOIN res_company aml_company', sql_code(sql))
            self.assertNotIn('acc.code_store', sql_code(sql))
            self.assertIn('acc.code', sql_code(sql))

    # ---- guardrails ----

    def test_company_scope_mandatory(self):
        with self.assertRaises(MoveLineQueryError):
            MoveLineQuery(self.env, company_ids=[])

    def test_select_required_before_build(self):
        with self.assertRaises(MoveLineQueryError):
            self._q().build()

    def test_unknown_field_rejected(self):
        with self.assertRaises(MoveLineQueryError):
            self._q().select_field('not_a_real_field')

    def test_unknown_account_field_rejected(self):
        with self.assertRaises(MoveLineQueryError):
            self._q().select_account_field('definitely_not_a_field')

    def test_unknown_groupable_field_rejected(self):
        q = self._q().select_balance_sum()
        with self.assertRaises(MoveLineQueryError):
            q.group_by('not_a_field')

    def test_invalid_alias_rejected(self):
        q = self._q()
        with self.assertRaises(MoveLineQueryError):
            q.select(SQL("SUM(aml.balance)"), 'has spaces')
        with self.assertRaises(MoveLineQueryError):
            q.select(SQL("SUM(aml.balance)"), '1leading_digit')
        with self.assertRaises(MoveLineQueryError):
            q.select(SQL("SUM(aml.balance)"), 'has-dashes')

    def test_invalid_direction_rejected(self):
        q = self._q().select_balance_sum()
        with self.assertRaises(MoveLineQueryError):
            q.order_by('date', direction='SIDEWAYS')

    # ---- mandatory filters ----

    def test_company_filter_always_present(self):
        sql = self._q().select_balance_sum().build()
        self.assertIn('aml.company_id IN', sql_code(sql))
        self.assertIn((self.cid,), sql_params(sql))

    def test_cancel_excluded_by_default(self):
        sql = self._q().select_balance_sum().build()
        self.assertIn('am.state != ', sql_code(sql))
        self.assertIn('cancel', sql_params(sql))

    def test_cancel_can_be_included(self):
        sql = self._q().select_balance_sum().where_include_cancelled().build()
        # 'cancel' should not be a parameter when cancellation is included.
        self.assertNotIn('cancel', sql_params(sql))

    def test_account_move_join_always_present(self):
        sql = self._q().select_balance_sum().build()
        self.assertIn('JOIN account_move am', sql_code(sql))

    # ---- selection ----

    def test_select_balance_sum_renders_alias(self):
        sql = self._q().select_balance_sum().build()
        self.assertIn('SUM(aml.balance)', sql_code(sql))
        self.assertIn('"balance"', sql_code(sql))

    def test_select_field_balanced(self):
        sql = self._q().select_field('account_id').select_balance_sum().build()
        self.assertIn('aml.account_id', sql_code(sql))
        self.assertIn('SUM(aml.balance)', sql_code(sql))

    def test_select_account_field_joins_account(self):
        sql = self._q().select_balance_sum().select_account_field('code').build()
        self.assertIn('JOIN account_account acc', sql_code(sql))
        self._assert_account_code_expression(sql)

    def test_multiple_selects_comma_separated(self):
        sql = (
            self._q()
            .select_field('account_id')
            .select_balance_sum()
            .select_count()
            .build()
        )
        # Three commas in the select list (between the four expressions, but
        # we count "AS" occurrences for stability).
        self.assertEqual(sql_code(sql).count(' AS '), 3)

    # ---- where filters ----

    def test_date_range_binds_params(self):
        sql = (
            self._q()
            .select_balance_sum()
            .where_date_range('2026-01-01', '2026-12-31')
            .build()
        )
        self.assertIn('aml.date >= ', sql_code(sql))
        self.assertIn('aml.date <= ', sql_code(sql))
        self.assertIn('2026-01-01', sql_params(sql))
        self.assertIn('2026-12-31', sql_params(sql))

    def test_journals_binds_tuple_param(self):
        sql = (
            self._q()
            .select_balance_sum()
            .where_journals([1, 2, 3])
            .build()
        )
        self.assertIn('aml.journal_id IN', sql_code(sql))
        self.assertIn((1, 2, 3), sql_params(sql))

    def test_account_codes_uses_like_with_percent_suffix(self):
        sql = (
            self._q()
            .select_balance_sum()
            .where_account_codes(['1', '20'])
            .build()
        )
        self.assertIn('JOIN account_account acc', sql_code(sql))
        self._assert_account_code_expression(sql)
        self.assertIn('LIKE', sql_code(sql))
        self.assertIn("ESCAPE '\\'", sql_code(sql))
        self.assertIn('1%', sql_params(sql))
        self.assertIn('20%', sql_params(sql))
        self.assertIn(' OR ', sql_code(sql))

    def test_account_types_filter(self):
        sql = (
            self._q()
            .select_balance_sum()
            .where_account_types(['income', 'expense'])
            .build()
        )
        self.assertIn('JOIN account_account acc', sql_code(sql))
        self.assertIn('acc.account_type IN', sql_code(sql))
        self.assertIn(('income', 'expense'), sql_params(sql))

    def test_partners_filter(self):
        sql = (
            self._q()
            .select_balance_sum()
            .where_partners([10, 20])
            .build()
        )
        self.assertIn('aml.partner_id IN', sql_code(sql))
        self.assertIn((10, 20), sql_params(sql))

    def test_posted_only_adds_state_filter(self):
        sql = (
            self._q()
            .select_balance_sum()
            .where_posted_only()
            .build()
        )
        self.assertIn('am.state = ', sql_code(sql))
        self.assertIn('posted', sql_params(sql))

    def test_posted_only_skips_redundant_cancel_filter(self):
        # When posted_only is set, the cancel exclusion is implied (cancel is
        # not 'posted'), so the builder skips emitting the redundant clause.
        sql = (
            self._q()
            .select_balance_sum()
            .where_posted_only()
            .build()
        )
        self.assertNotIn('cancel', sql_params(sql))

    def test_order_by_account_field_joins_account(self):
        sql = (
            self._q()
            .select_balance_sum()
            .order_by_account_field('code', 'ASC')
            .build()
        )
        self.assertIn('JOIN account_account acc', sql_code(sql))
        self._assert_account_code_expression(sql)
        self.assertIn('ASC', sql_code(sql))

    def test_join_journal_emits_clause(self):
        q = self._q().select_balance_sum().join_journal()
        q.select(SQL("aj.code"), 'journal_code')
        sql = q.build()
        self.assertIn('JOIN account_journal aj', sql_code(sql))
        self.assertIn('aj.code', sql_code(sql))

    def test_join_partner_emits_left_join(self):
        q = self._q().select_balance_sum().join_partner()
        q.select(SQL("p.name"), 'partner_name')
        sql = q.build()
        self.assertIn('LEFT JOIN res_partner p', sql_code(sql))
        self.assertIn('p.name', sql_code(sql))

    def test_join_account_public_method(self):
        q = self._q().select_balance_sum().join_account()
        q.select(SQL("acc.code"), 'account_code')
        sql = q.build()
        self.assertIn('JOIN account_account acc', sql_code(sql))

    def test_joins_emitted_only_once_per_table(self):
        q = (
            self._q()
            .select_balance_sum()
            .join_journal()
            .join_journal()  # second call must be idempotent
            .join_partner()
            .join_partner()
        )
        q.select(SQL("aj.code"), 'journal_code')
        q.select(SQL("p.name"), 'partner_name')
        sql = q.build()
        self.assertEqual(sql_code(sql).count('JOIN account_journal aj'), 1)
        self.assertEqual(sql_code(sql).count('LEFT JOIN res_partner p'), 1)

    def test_empty_filters_are_no_op(self):
        sql = (
            self._q()
            .select_balance_sum()
            .where_journals([])
            .where_partners([])
            .where_accounts([])
            .where_account_codes([])
            .where_account_types([])
            .where_analytic_accounts([])
            .build()
        )
        # Mandatory: company + cancel state. Plus the auto join on account_move.
        # No additional filters should appear beyond those two.
        self.assertEqual(sql_code(sql).count(' AND '), 1)

    def test_where_analytic_accounts_matches_composite_jsonb_keys(self):
        sql = (
            self._q()
            .select_balance_sum()
            .where_analytic_accounts([3, 7])
            .build()
        )
        self.assertIn('jsonb_object_keys', sql_code(sql))
        self.assertIn("jsonb_typeof(aml.analytic_distribution)", sql_code(sql))
        self.assertIn("ELSE '{}'::jsonb", sql_code(sql))
        self.assertIn('string_to_array', sql_code(sql))
        self.assertIn('&&', sql_code(sql))
        # Preserve the index-friendly whole-key path for ordinary one-plan
        # distributions, then fall back to token matching for composites.
        self.assertIn('analytic_distribution ?|', sql_code(sql))
        # Keys are passed as a string array and compared with every token in
        # both simple keys ("3") and cross-plan composite keys ("3,11").
        params = list(sql_params(sql) or ())
        # Two copies belong to the inclusive key predicate and one to the
        # monetary analytic-weight expression.
        self.assertEqual(params.count(['3', '7']), 3)

    def test_analytic_filter_weights_monetary_selector_added_first(self):
        sql = (
            self._q()
            .select_balance_sum()
            .where_analytic_accounts([3, 7])
            .build()
        )
        self.assertIn('jsonb_each', sql_code(sql))
        self.assertIn("jsonb_typeof(analytic_part.value) = 'number'", sql_code(sql))
        self.assertIn('/ 100.0', sql_code(sql))
        self.assertEqual(list(sql_params(sql)).count(['3', '7']), 3)

    def test_column_analytic_intersects_global_and_owns_weight(self):
        sql = (
            self._q()
            .select_balance_sum()
            .where_analytic_accounts([3])
            .where_analytic_column_accounts([7])
            .build()
        )
        params = list(sql_params(sql) or ())
        # Two membership binds per scope.  Only column 7 owns allocation
        # weighting, so it has one additional bind and 3 never weights value.
        self.assertEqual(params.count(['3']), 2)
        self.assertEqual(params.count(['7']), 3)
        self.assertNotIn(['3', '7'], params)

    def test_empty_analytic_column_group_fails_closed(self):
        sql = (
            self._q()
            .select_balance_sum()
            .where_analytic_column_accounts([], require_match=True)
            .build()
        )
        self.assertIn('FALSE', sql_code(sql))

    # ---- group / order / limit ----

    def test_group_by_field(self):
        sql = (
            self._q()
            .select_field('account_id')
            .select_balance_sum()
            .group_by('account_id')
            .build()
        )
        self.assertIn('GROUP BY aml.account_id', sql_code(sql))

    def test_group_by_multiple_fields(self):
        sql = (
            self._q()
            .select_field('account_id')
            .select_field('partner_id')
            .select_balance_sum()
            .group_by('account_id', 'partner_id')
            .build()
        )
        self.assertIn('GROUP BY', sql_code(sql))
        self.assertIn('aml.account_id', sql_code(sql))
        self.assertIn('aml.partner_id', sql_code(sql))

    def test_order_by_field_with_direction(self):
        sql = (
            self._q()
            .select_balance_sum()
            .order_by('date', direction='DESC')
            .build()
        )
        self.assertIn('ORDER BY', sql_code(sql))
        self.assertIn('aml.date DESC', sql_code(sql))

    def test_limit_and_offset(self):
        sql = (
            self._q()
            .select_balance_sum()
            .limit(50)
            .offset(100)
            .build()
        )
        self.assertIn('LIMIT', sql_code(sql))
        self.assertIn('OFFSET', sql_code(sql))
        self.assertIn(50, sql_params(sql))
        self.assertIn(100, sql_params(sql))

    def test_offset_zero_omitted(self):
        sql = (
            self._q()
            .select_balance_sum()
            .offset(0)
            .build()
        )
        self.assertNotIn('OFFSET', sql_code(sql))

    def test_limit_none_omitted(self):
        sql = (
            self._q()
            .select_balance_sum()
            .limit(None)
            .build()
        )
        self.assertNotIn('LIMIT', sql_code(sql))

    # ---- multi company ----

    def test_multi_company_scope(self):
        with self.env.cr.savepoint():
            try:
                other = self.env['res.company'].with_context(
                    default_group_rfq='default',
                ).create({'name': 'Other Co'})
            except Exception as exc:
                # Upstream stock + Enterprise ai_fields interaction
                # can strip NOT NULL defaults on per-company
                # auto-records (warehouse picking types). The query
                # builder's company_ids logic is exercised in many
                # other tests; skip here when company creation is
                # impossible.
                self.skipTest(
                    f"environment cannot create a second company: {exc}"
                )
                return
        sql = MoveLineQuery(self.env, company_ids=[self.cid, other.id]) \
            .select_balance_sum() \
            .build()
        # Tuple param order is sorted to (cid, other.id) by build path.
        self.assertIn(self.cid, sql_params(sql)[0])
        self.assertIn(other.id, sql_params(sql)[0])

    # ---- raw escape hatch ----

    def test_where_raw_appends_fragment(self):
        sql = (
            self._q()
            .select_balance_sum()
            .where_raw(SQL("aml.amount_currency > %s", 0))
            .build()
        )
        self.assertIn('aml.amount_currency >', sql_code(sql))
        self.assertIn(0, sql_params(sql))

    def test_where_raw_rejects_non_sql(self):
        q = self._q().select_balance_sum()
        with self.assertRaises(MoveLineQueryError):
            q.where_raw("aml.balance > 0")

    # ---- safety: SQL injection paths ----

    def test_select_alias_blocks_sql_injection_attempt(self):
        q = self._q()
        with self.assertRaises(MoveLineQueryError):
            q.select(SQL("SUM(aml.balance)"), 'balance"; DROP TABLE--')

    def test_account_code_prefix_treats_like_metacharacters_literally(self):
        sql = (
            self._q()
            .select_balance_sum()
            .where_account_codes([r'1%_\prefix'])
            .build()
        )
        self._assert_account_code_expression(sql)
        self.assertIn("LIKE %s ESCAPE '\\'", sql_code(sql))
        self.assertIn(r'1\%\_\\prefix%', sql_params(sql))


@tagged('eh_account_base', 'unit')
class TestMoveLineQueryCurrencyConversion(EhAccountUnitTestCase):
    """WS4: select_*_sum_converted + the currency-table LEFT JOIN.

    These are pure shape assertions (the SQL is inspected, never executed),
    proving:

    * With no currency table, or a monocurrency one, the rendered SQL is
      byte-identical to the legacy select_balance_sum path (regression guard
      on the single-currency hot path that 95% of installs run).
    * With a multicurrency table attached, the converted sums render the
      ``* ct.rate`` multiply and build() emits the complete per-company
      VALUES join, with no identity fallback.
    """

    def setUp(self):
        super().setUp()
        self.cid = self.env.company.id

    def _q(self, **kw):
        return MoveLineQuery(self.env, company_ids=[self.cid], **kw)

    def _multicurrency_table(self, rate_map):
        """A CurrencyTable forced into multicurrency mode with a fixed map.

        Bypasses ORM rate seeding (white-box) so the test does not depend on
        creating two real different-currency companies in the registry.
        """
        from odoo.addons.eh_account_base.tools.currency_table import (
            CurrencyTable,
        )
        ct = CurrencyTable(
            self.env, company_ids=list(rate_map.keys()),
            presentation_currency_id=self.env.company.currency_id.id,
            rate_map=rate_map,
        )
        ct._is_monocurrency = False  # force the conversion path
        return ct

    # ---- regression guard: byte-identical without conversion ----

    def test_converted_sum_byte_identical_without_table(self):
        plain = self._q().select_balance_sum().build()
        converted = self._q().select_balance_sum_converted().build()
        self.assertEqual(sql_code(plain), sql_code(converted))
        self.assertEqual(sql_params(plain), sql_params(converted))

    def test_converted_sum_byte_identical_with_monocurrency_table(self):
        # A monocurrency table (single company) must add NO join and NO
        # multiply: the rendered SQL equals the no-table form exactly.
        ct = self._multicurrency_table({self.cid: 1.0})
        ct._is_monocurrency = True  # monocurrency: zero-overhead path
        plain = self._q().select_balance_sum().build()
        q = MoveLineQuery(
            self.env, company_ids=[self.cid], currency_table=ct,
        )
        with_table = q.select_balance_sum_converted().build()
        self.assertEqual(sql_code(plain), sql_code(with_table))
        self.assertEqual(sql_params(plain), sql_params(with_table))
        self.assertNotIn('ct.rate', sql_code(with_table))
        self.assertNotIn('LEFT JOIN (VALUES', sql_code(with_table))

    # ---- multicurrency rendering ----

    def test_converted_balance_renders_rate_multiply(self):
        ct = self._multicurrency_table({self.cid: 1.5})
        q = MoveLineQuery(
            self.env, company_ids=[self.cid], currency_table=ct,
        )
        sql = q.select_balance_sum_converted().build()
        self.assertIn('ct.rate', sql_code(sql))
        self.assertNotIn('COALESCE(ct.rate, 1)', sql_code(sql))
        self.assertIn('aml.balance', sql_code(sql))
        self.assertIn('JOIN (VALUES', sql_code(sql))
        # The aml alias is bound as a quoted identifier for injection safety.
        self.assertIn('ct.company_id = "aml".company_id', sql_code(sql))
        # The seeded rate is bound as a param, never interpolated.
        self.assertIn(1.5, sql_params(sql))

    def test_converted_debit_and_credit_render_rate_multiply(self):
        ct = self._multicurrency_table({self.cid: 2.0})
        q = MoveLineQuery(
            self.env, company_ids=[self.cid], currency_table=ct,
        )
        sql = (
            q.select_debit_sum_converted()
            .select_credit_sum_converted()
            .build()
        )
        self.assertEqual(sql_code(sql).count('ct.rate'), 2)
        self.assertNotIn('COALESCE(ct.rate, 1)', sql_code(sql))
        self.assertIn('aml.debit', sql_code(sql))
        self.assertIn('aml.credit', sql_code(sql))

    def test_single_company_different_target_requires_conversion(self):
        from odoo.addons.eh_account_base.tools.currency_table import (
            CurrencyTable,
        )
        target = self.env['res.currency'].create({
            'name': 'SCT', 'symbol': 'S', 'rounding': 0.01,
        })
        ct = CurrencyTable(
            self.env,
            company_ids=[self.cid],
            presentation_currency_id=target.id,
            rate_map={self.cid: 2.0},
        )
        self.assertFalse(ct.is_monocurrency)
        sql = MoveLineQuery(
            self.env, company_ids=[self.cid], currency_table=ct,
        ).select_balance_converted().build()
        self.assertIn('ct.rate', sql_code(sql))
        self.assertNotIn('COALESCE(ct.rate, 1)', sql_code(sql))
        self.assertIn('JOIN (VALUES', sql_code(sql))

    def test_multicurrency_join_emitted_only_once(self):
        ct = self._multicurrency_table({self.cid: 1.25})
        q = MoveLineQuery(
            self.env, company_ids=[self.cid], currency_table=ct,
        )
        sql = (
            q.select_balance_sum_converted()
            .select_debit_sum_converted()
            .build()
        )
        # One rate join regardless of how many converted sums are selected.
        self.assertEqual(sql_code(sql).count('JOIN (VALUES'), 1)

    def test_multicurrency_join_rejects_incomplete_or_invalid_rate_map(self):
        missing = self._multicurrency_table({self.cid: 1.25})
        missing.company_ids = (self.cid, self.cid + 999999)
        with self.assertRaises(UserError):
            missing.join_sql()

        for rate in (0.0, float('nan'), float('inf')):
            invalid = self._multicurrency_table({self.cid: rate})
            with self.subTest(rate=rate), self.assertRaises(UserError):
                invalid.join_sql()

    def test_plain_select_balance_sum_unaffected_by_attached_table(self):
        # select_balance_sum (the legacy method) must NOT convert even when a
        # multicurrency table is attached; only the *_converted variants do.
        ct = self._multicurrency_table({self.cid: 9.0})
        q = MoveLineQuery(
            self.env, company_ids=[self.cid], currency_table=ct,
        )
        sql = q.select_balance_sum().build()
        self.assertNotIn('ct.rate', sql_code(sql).split('LEFT JOIN')[0])
