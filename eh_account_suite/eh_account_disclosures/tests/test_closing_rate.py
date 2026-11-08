# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Reporting-date translations use the closing rate OF the reporting date.

Odoo 20 ``res.currency._convert(date=D)`` reads the latest rate dated
strictly before D. The FX revaluation books, and the consolidation
translates, at the rate row dated on the reporting date, so the IFRS 7 and
IFRS 12 figures must use that same row or they no longer tie to the books.
"""

import ast
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.eh_account_base.tests.golden_common import EhGoldenTestCase
from odoo.addons.eh_account_disclosures.models.integrity import (
    closing_convert,
)


class _FakeLines(list):
    def filtered(self, function):
        return _FakeLines(item for item in self if function(item))

    def mapped(self, name):
        return [getattr(item, name) for item in self]


@tagged('eh_account_disclosures', 'post_install', '-at_install')
class TestDisclosureClosingRate(EhGoldenTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= cls.env.ref(
            'eh_account_base.group_eh_manager')
        cls.eur = cls.env.ref('base.EUR')
        cls.usd = cls.company.currency_id
        # Units of EUR per 1 USD: the day before, the reporting date and the
        # day after all carry a different rate so the row used is provable.
        cls._set_rate(cls.eur, date(2031, 6, 29), 0.8)   # 1 EUR = 1.25 USD
        cls._set_rate(cls.eur, date(2031, 6, 30), 0.5)   # 1 EUR = 2.00 USD
        cls._set_rate(cls.eur, date(2031, 7, 1), 0.25)   # 1 EUR = 4.00 USD
        cls.reporting_date = date(2031, 6, 30)

    def test_helper_applies_rate_dated_on_reporting_date(self):
        self.assertAlmostEqual(closing_convert(
            1000.0, self.eur, self.usd, self.company, self.reporting_date,
        ), 2000.0, places=2)
        # Core alone would have used the previous day's row.
        self.assertAlmostEqual(self.eur._convert(
            1000.0, self.usd, self.company, self.reporting_date,
        ), 1250.0, places=2)

    def test_fx_sensitivity_exposure_ties_to_closing_rate(self):
        """1,000 EUR net position at 30 Jun is 2,000 USD, as revalued."""
        sens = self.env['eh.fin.sensitivity'].create({
            'reporting_date': self.reporting_date,
            'fx_shock_pct': 10.0,
        })
        with patch.object(
            type(sens), '_fx_open_positions',
            lambda record: {self.eur: 1000.0},
        ):
            vals_list = sens._fx_line_vals()
        self.assertEqual(len(vals_list), 1)
        self.assertAlmostEqual(vals_list[0]['exposure'], 2000.0, places=2)
        self.assertAlmostEqual(vals_list[0]['pnl_impact'], 200.0, places=2)

    def test_entity_interest_retranslates_at_run_closing_rate(self):
        interest = self.env['eh.entity.interest'].create({
            'name': 'Closing rate member',
        })
        member = SimpleNamespace(
            ownership_pct=100.0, method='full', display_name='Member',
        )
        lines = _FakeLines([
            SimpleNamespace(
                member_id=member, kind='subsidiary_balance', amount=1000.0,
                account_id=SimpleNamespace(account_type='asset_current'),
            ),
        ])
        run = SimpleNamespace(
            id=778, display_name='EUR run',
            presentation_currency_id=self.eur,
            period_to=self.reporting_date, line_ids=lines,
        )
        interest._apply_consolidation_figures(run, member)
        self.assertEqual(interest.currency_id, self.usd)
        self.assertAlmostEqual(interest.summarised_assets, 2000.0, places=2)

    def test_no_reporting_date_conversion_bypasses_closing_helper(self):
        """Every conversion dated on the reporting date or the run period end
        goes through ``closing_convert``; a direct ``_convert`` would silently
        pick the previous day's rate on Odoo 20."""
        models_dir = Path(__file__).resolve().parent.parent / 'models'
        offenders = []
        for path in sorted(models_dir.glob('*.py')):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == '_convert'):
                    continue
                dated = ast.unparse(node)
                if 'reporting_date' in dated or 'period_to' in dated:
                    offenders.append('%s:%s' % (path.name, node.lineno))
        self.assertFalse(offenders, (
            "Reporting-date conversions must use closing_convert: %s"
            % ', '.join(offenders)))
