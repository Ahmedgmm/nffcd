# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################

from unittest.mock import patch

from odoo.tests import TransactionCase

from odoo.addons.eh_account_base.tools import orm_compat


class _OldReadGroupProbe:

    def __init__(self, env):
        self.env = env
        self._fields = {
            'partner_id': env['account.move']._fields['partner_id'],
        }
        self.fields = None

    def read_group(self, domain, fields, groupby, lazy=True):  # odoo20-sweep: ok fake Odoo 16 model for the legacy branch test
        self.fields = fields
        return []


class TestListStatistics(TransactionCase):

    def setUp(self):
        super().setUp()
        self.mixin = self.env['eh.list.statistics.mixin']

    def test_empty_and_partial_payloads_are_safe(self):
        self.assertEqual(self.mixin._eh_sanitize_list_statistics(False), [])
        self.assertEqual(self.mixin._eh_sanitize_list_statistics({}), [])

        result = self.mixin._eh_sanitize_list_statistics([
            None,
            {'value': None},
            {'value': float('nan')},
            {
                'iconClass': 'not an icon',
                'value': 3,
                'label': None,
                'tagClass': 'not a tag',
            },
        ])
        # Odoo 20 statistics carry a Material Symbols ``icon``; unknown
        # classes degrade to the neutral circle icon.
        self.assertEqual(result, [{
            'icon': 'circle',
            'value': 3,
            'label': 'Statistic',
        }])

    def test_payload_is_bounded_and_only_known_classes_survive(self):
        entries = [{
            'iconClass': 'fa-check',
            'value': index,
            'label': 'Verified',
            'tagClass': 'o_tag_color_11',
        } for index in range(12)]
        result = self.mixin._eh_sanitize_list_statistics(entries)
        self.assertEqual(len(result), 8)
        # A legacy Font Awesome class maps to its Material Symbols icon.
        self.assertEqual(result[0], {
            'icon': 'check',
            'value': 0,
            'label': 'Verified',
            'tagClass': 'o_tag_color_11',
        })

    def test_odoo20_icon_contract_and_legacy_font_awesome_mapping(self):
        result = self.mixin._eh_sanitize_list_statistics([
            # Core Odoo 20 contract: Material Symbols name plus modifier.
            {'icon': 'star', 'iconClass': 'oi-filled', 'value': 1,
             'label': 'Native'},
            # Every legacy class the suite still sends has an equivalent.
            {'iconClass': 'fa-hourglass-half', 'value': 2, 'label': 'Legacy'},
            # Markup or class injection never reaches the template.
            {'icon': 'star" onclick="x', 'iconClass': 'btn btn-danger',
             'value': 3, 'label': 'Hostile'},
            # An explicit icon wins over a legacy class.
            {'icon': 'payments', 'iconClass': 'fa-money', 'value': 4,
             'label': 'Both'},
        ])
        self.assertEqual(
            [(entry['icon'], entry.get('iconClass')) for entry in result],
            [
                ('star', 'oi-filled'),
                ('hourglass_top', None),
                ('circle', None),
                ('payments', None),
            ],
        )

    def test_only_safe_action_methods_survive(self):
        result = self.mixin._eh_sanitize_list_statistics([
            {
                'iconClass': 'fa-check',
                'value': 1,
                'label': 'Safe',
                'actionMethod': 'action_view_safe_records',
            },
            {
                'iconClass': 'fa-check',
                'value': 2,
                'label': 'Workflow',
                'actionMethod': 'action_post_records',
            },
            {
                'iconClass': 'fa-check',
                'value': 3,
                'label': 'Private',
                'actionMethod': '_action_private',
            },
            {
                'iconClass': 'fa-check',
                'value': 4,
                'label': 'Mixed case',
                'actionMethod': 'action_View_Unsafe',
            },
            {
                'iconClass': 'fa-check',
                'value': 5,
                'label': 'Punctuation',
                'actionMethod': 'action_view-unsafe',
            },
            {
                'iconClass': 'fa-check',
                'value': 6,
                'label': 'Wrong type',
                'actionMethod': ['action_view_unsafe'],
            },
        ])
        self.assertEqual(
            result[0]['actionMethod'], 'action_view_safe_records',
        )
        for entry in result[1:]:
            self.assertNotIn('actionMethod', entry)

    def test_odoo16_count_only_grouping_never_requests_all_fields(self):
        probe = _OldReadGroupProbe(self.env)
        with patch.object(orm_compat, '_NEW_READ_GROUP', False):
            result = orm_compat.read_group_compat(
                probe,
                [],
                ['partner_id'],
                ['__count'],
            )
        self.assertEqual(result, [])
        self.assertEqual(probe.fields, ['partner_id'])

        with patch.object(orm_compat, '_NEW_READ_GROUP', False):
            result = orm_compat.read_group_compat(
                probe,
                [],
                [],
                ['__count'],
            )
        self.assertEqual(result, [])
        self.assertEqual(probe.fields, ['__count'])
