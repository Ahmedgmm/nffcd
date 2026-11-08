# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Small, read-only list statistics shared by accounting-suite models.

Statistics remain non-stored and are computed for the prefetched list-page
recordset.  Contributors must batch their reads; this mixin deliberately does
not perform a query or persist a counter itself.
"""

import math
import re
from collections import defaultdict

from odoo import api, fields, models


# Odoo 20 dropped Font Awesome from the web client: icons are Material
# Symbols ligatures rendered as ``<i class="oi" data-icon="name"/>``, the same
# ``icon`` / ``iconClass`` contract core application statistics use.
_ICON_NAME_RE = re.compile(r'^[a-z0-9_]+$')
_ICON_MODIFIER_CLASSES = frozenset({'oi-filled'})
_DEFAULT_ICON = 'circle'
# Extensions written for the Font Awesome era still send ``iconClass:
# 'fa-*'``. Keep them rendering through their Material Symbols equivalent;
# mirrored by LEGACY_FA_ICONS in list_statistics.js.
_LEGACY_FA_ICONS = {
    'fa-check': 'check',
    'fa-check-circle': 'check_circle',
    'fa-circle': 'circle',
    'fa-credit-card': 'credit_card',
    'fa-cube': 'deployed_code',
    'fa-exclamation-triangle': 'warning',
    'fa-file-text-o': 'description',
    'fa-hourglass-half': 'hourglass_top',
    'fa-link': 'link',
    'fa-list': 'format_list_bulleted',
    'fa-money': 'payments',
    'fa-pencil-square-o': 'edit_square',
}
_TAG_CLASS_RE = re.compile(r'^o_tag_color_(?:[0-9]|1[01])$')
# Statistics are a non-stored, read-only payload produced by trusted Python
# hooks.  Keep client-callable methods inside the suite's view-only naming
# convention; workflow/mutation methods never cross this boundary.
_ACTION_METHOD_RE = re.compile(r'^action_view_[a-z0-9_]+$')
_MAX_STATISTICS = 8
_MAX_LABEL_LENGTH = 80
_MAX_VALUE_LENGTH = 40


class EhListStatisticsMixin(models.AbstractModel):
    _name = 'eh.list.statistics.mixin'
    _description = 'ERP Heritage List Statistics Mixin'

    eh_list_statistics = fields.Json(
        string='Statistics',
        compute='_compute_eh_list_statistics',
        readonly=True,
    )

    @api.depends_context('uid', 'allowed_company_ids', 'company')
    def _compute_eh_list_statistics(self):
        statistics_by_record = self._eh_list_statistics_hook() or {}
        for record in self:
            entries = statistics_by_record.get(record.id, [])
            record.eh_list_statistics = self._eh_sanitize_list_statistics(
                entries,
            )

    def _eh_list_statistics_hook(self):
        """Return ``record id -> badge payloads`` for this recordset.

        Overrides append to the returned lists and must batch any database
        work across ``self``.  Returning an empty mapping is query-free and
        gives every row an empty payload (``fields.Json`` may expose it as
        ``False`` on older series).
        """
        return defaultdict(list)

    @api.model
    def _eh_sanitize_list_statistics(self, entries):
        """Normalize an extension payload without failing list rendering."""
        if not isinstance(entries, (list, tuple)):
            return []

        sanitized = []
        for entry in entries:
            if len(sanitized) >= _MAX_STATISTICS:
                break
            if not isinstance(entry, dict):
                continue

            value = entry.get('value')
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, float) and not math.isfinite(value):
                continue
            if not isinstance(value, (int, float, str)):
                continue
            if isinstance(value, str):
                value = value[:_MAX_VALUE_LENGTH]

            icon, icon_class = self._eh_normalize_statistic_icon(entry)

            label = entry.get('label')
            try:
                label = str(label) if label else self.env._('Statistic')
            except (TypeError, ValueError):
                label = self.env._('Statistic')

            result = {
                'icon': icon,
                'value': value,
                'label': label[:_MAX_LABEL_LENGTH],
            }
            if icon_class:
                result['iconClass'] = icon_class
            tag_class = entry.get('tagClass')
            if isinstance(tag_class, str) and _TAG_CLASS_RE.fullmatch(
                    tag_class):
                result['tagClass'] = tag_class
            action_method = entry.get('actionMethod')
            if (
                isinstance(action_method, str)
                and _ACTION_METHOD_RE.fullmatch(action_method)
            ):
                result['actionMethod'] = action_method
            sanitized.append(result)
        return sanitized

    @api.model
    def _eh_normalize_statistic_icon(self, entry):
        """Return ``(icon, icon_class)`` for one statistic payload.

        ``icon`` is a Material Symbols name; ``icon_class`` is an optional
        style modifier (``oi-filled``). A legacy Font Awesome ``iconClass``
        maps to its Material Symbols equivalent, anything else falls back to
        the neutral ``circle`` icon.
        """
        icon = entry.get('icon')
        icon_class = entry.get('iconClass')
        if not isinstance(icon, str) or not _ICON_NAME_RE.fullmatch(icon):
            icon = False
        if not isinstance(icon_class, str):
            icon_class = False
        if not icon and icon_class:
            icon = _LEGACY_FA_ICONS.get(icon_class, False)
        if icon_class not in _ICON_MODIFIER_CLASSES:
            icon_class = False
        return icon or _DEFAULT_ICON, icon_class
