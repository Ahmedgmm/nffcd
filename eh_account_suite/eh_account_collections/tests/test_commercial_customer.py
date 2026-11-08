# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Open cases follow the Odoo 20 commercial customer.

Odoo 20 makes the topmost parent the commercial partner; Odoo 19 stopped at
the first company. A case opened on a subsidiary that was its own commercial
customer must not stay open next to a second case for its parent.
"""

import importlib.util
from datetime import timedelta
from pathlib import Path

from odoo import fields
from odoo.tests import tagged

from odoo.addons.eh_account_base.tests.common import EhAccountIntegrationTestCase


@tagged('eh_account_collections', 'integration', 'post_install', '-at_install')
class TestCommercialCustomerCases(EhAccountIntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Case = cls.env['eh.collections.case']
        cls.today = fields.Date.context_today(cls.env['res.users'])
        cls.company.eh_collections_grace_days = 0

    def _overdue(self, partner, amount, days_overdue):
        return self.post_balanced_move(
            [
                {
                    'account': self.account_receivable,
                    'debit': amount,
                    'partner': partner,
                    'date_maturity': self.today - timedelta(days=days_overdue),
                },
                {'account': self.account_revenue, 'credit': amount},
            ],
            date=self.today - timedelta(days=days_overdue + 30),
        )

    def _subsidiary_with_open_case(self):
        """The Odoo 19 state: the subsidiary's own open case, then Odoo 20
        re-points the subsidiary's commercial customer to its parent."""
        group = self.env['res.partner'].create({'name': 'Group Holdings'})
        sub = self.env['res.partner'].create({'name': 'Sub Pty Ltd'})
        self._overdue(sub, 45000.0, days_overdue=45)
        case = self.Case.create({
            'partner_id': sub.id, 'company_id': self.company.id,
        })
        self.assertEqual(case.partner_id, sub)
        sub.parent_id = group
        self.assertEqual(sub.commercial_partner_id, group)
        return group, sub, case

    def _open_cases(self, partners):
        return self.Case.search([
            ('partner_id', 'in', partners.ids),
            ('company_id', '=', self.company.id),
            ('is_resolved', '=', False),
        ])

    def test_auto_create_moves_case_instead_of_opening_a_second(self):
        group, sub, case = self._subsidiary_with_open_case()
        self.Case.auto_create_cases([self.company.id])
        # Other overdue customers (demo data) may get cases of their own;
        # the group must end up with exactly the subsidiary's case, moved.
        open_cases = self._open_cases(group | sub)
        self.assertEqual(open_cases, case)
        self.assertEqual(case.partner_id, group)
        self.assertAlmostEqual(case.total_overdue_amount, 45000.0, places=2)

    def test_case_is_resolved_into_existing_commercial_customer_case(self):
        group, sub, case = self._subsidiary_with_open_case()
        group_case = self.Case.create({
            'partner_id': group.id, 'company_id': self.company.id,
        })
        self.Case._cron_refresh_open_cases()
        self.assertTrue(case.is_resolved)
        self.assertEqual(self._open_cases(group | sub), group_case)
        self.assertAlmostEqual(
            group_case.total_overdue_amount, 45000.0, places=2)

    def test_upgrade_rehomes_open_subsidiary_cases(self):
        group, sub, case = self._subsidiary_with_open_case()
        path = (
            Path(__file__).parents[1] / 'migrations' / '20.0.1.2.8'
            / 'post-commercial-customer.py'
        )
        spec = importlib.util.spec_from_file_location(
            'eh_collections_commercial_customer_migration_test', path,
        )
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with self.assertLogs(
            'eh_collections_commercial_customer_migration_test',
            level='WARNING',
        ) as captured:
            migration.migrate(self.env.cr, '19.0.1.2.8')
        self.env.invalidate_all()
        self.assertIn('1 open case(s)', '\n'.join(captured.output))
        self.assertEqual(case.partner_id, group)
        self.assertEqual(self._open_cases(group | sub), case)
