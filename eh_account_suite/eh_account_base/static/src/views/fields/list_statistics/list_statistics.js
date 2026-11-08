// ============================================================================
// ERP Heritage
// Copyright (C) 2026 (https://www.erpheritage.com.au/)
// ============================================================================

import { Component, usePlugin, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { ActionPlugin } from "@web/webclient/actions/action_plugin";

// Odoo 20 renders icons as Material Symbols ligatures
// (<i class="oi" data-icon="name"/>), the same icon / iconClass contract the
// core contact statistics use. Font Awesome is no longer shipped.
const ICON_NAME_RE = /^[a-z0-9_]+$/;
const ICON_MODIFIER_CLASSES = new Set(["oi-filled"]);
const DEFAULT_ICON = "circle";
// Payloads written for the Font Awesome era keep rendering through their
// Material Symbols equivalent. Mirrors _LEGACY_FA_ICONS in
// models/list_statistics.py.
const LEGACY_FA_ICONS = {
    "fa-check": "check", // odoo20-sweep: ok legacy payload name mapped to Material
    "fa-check-circle": "check_circle", // odoo20-sweep: ok legacy payload name mapped to Material
    "fa-circle": "circle", // odoo20-sweep: ok legacy payload name mapped to Material
    "fa-credit-card": "credit_card", // odoo20-sweep: ok legacy payload name mapped to Material
    "fa-cube": "deployed_code", // odoo20-sweep: ok legacy payload name mapped to Material
    "fa-exclamation-triangle": "warning", // odoo20-sweep: ok legacy payload name mapped to Material
    "fa-file-text-o": "description", // odoo20-sweep: ok legacy payload name mapped to Material
    "fa-hourglass-half": "hourglass_top", // odoo20-sweep: ok legacy payload name mapped to Material
    "fa-link": "link", // odoo20-sweep: ok legacy payload name mapped to Material
    "fa-list": "format_list_bulleted", // odoo20-sweep: ok legacy payload name mapped to Material
    "fa-money": "payments", // odoo20-sweep: ok legacy payload name mapped to Material
    "fa-pencil-square-o": "edit_square", // odoo20-sweep: ok legacy payload name mapped to Material
};
const TAG_CLASS_RE = /^o_tag_color_(?:[0-9]|1[01])$/;
const ACTION_METHOD_RE = /^action_view_[a-z0-9_]+$/;

function cleanClassToken(value, pattern) {
    if (typeof value !== "string") {
        return "";
    }
    const token = value.trim();
    return pattern.test(token) ? token : "";
}

/**
 * Resolve the Material Symbols icon name and optional style modifier of one
 * statistic, accepting both the Odoo 20 contract and legacy Font Awesome
 * classes.
 */
export function normalizeStatisticIcon(value) {
    const rawIcon = typeof value.icon === "string" ? value.icon.trim() : "";
    const rawClass =
        typeof value.iconClass === "string" ? value.iconClass.trim() : "";
    let icon = ICON_NAME_RE.test(rawIcon) ? rawIcon : "";
    if (!icon && rawClass) {
        icon = LEGACY_FA_ICONS[rawClass] || "";
    }
    return {
        icon: icon || DEFAULT_ICON,
        iconClass: ICON_MODIFIER_CLASSES.has(rawClass) ? rawClass : "",
    };
}

/**
 * Convert one server statistic into safe, predictable template data.
 *
 * Invalid entries disappear instead of breaking whole list row. Zero remains
 * valid. Missing/invalid optional classes degrade to neutral Odoo badge.
 */
export function normalizeListStatistic(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
        return null;
    }

    const valueType = typeof value.value;
    const hasDisplayValue =
        (valueType === "number" && Number.isFinite(value.value)) ||
        (valueType === "string" && value.value.trim() !== "");
    const label = typeof value.label === "string" ? value.label.trim() : "";
    if (!hasDisplayValue || !label) {
        return null;
    }

    return {
        // This value originates in trusted, read-only Python hooks. Repeat
        // the server's view-only allowlist here so malformed legacy/cache
        // payloads can never turn a badge into an arbitrary model RPC.
        actionMethod:
            typeof value.actionMethod === "string" &&
            ACTION_METHOD_RE.test(value.actionMethod)
                ? value.actionMethod
                : "",
        ...normalizeStatisticIcon(value),
        label,
        tagClass: cleanClassToken(value.tagClass, TAG_CLASS_RE),
        value: value.value,
    };
}

export class EhListStatisticsField extends Component {
    static template = "eh_account_base.EhListStatisticsField";

    props = useProps({
        ...standardFieldProps,
    });

    setup() {
        this.orm = useService("orm");
        this.actionService = usePlugin(ActionPlugin);
        this.openingAction = false;
    }

    get statistics() {
        const record = this.props.record;
        const rawValue = record && record.data
            ? record.data[this.props.name]
            : null;
        if (!Array.isArray(rawValue)) {
            return [];
        }
        return rawValue.map(normalizeListStatistic).filter(Boolean);
    }

    async openStatistic(statistic) {
        const record = this.props.record;
        const actionMethod = statistic && statistic.actionMethod;
        if (
            this.openingAction ||
            typeof actionMethod !== "string" ||
            !ACTION_METHOD_RE.test(actionMethod) ||
            !record ||
            typeof record.resModel !== "string" ||
            !record.resModel.trim() ||
            !Number.isInteger(record.resId) ||
            record.resId <= 0
        ) {
            return;
        }

        this.openingAction = true;
        try {
            const action = await this.orm.call(
                record.resModel,
                actionMethod,
                [[record.resId]],
            );
            if (action) {
                await this.actionService.doAction(action);
            }
        } finally {
            this.openingAction = false;
        }
    }
}

// EH_LIST_STATS_ODOO16_REGISTRATION_START
// Odoo 17 and later field registries consume descriptor objects. Backporter
// replaces only this marked block with Odoo 16 direct-component registrations.
export const ehListStatisticsField = {
    component: EhListStatisticsField,
    displayName: _t("List Statistics"),
    supportedTypes: ["json"],
};

registry.category("fields").add("eh_list_statistics", ehListStatisticsField);
// EH_LIST_STATS_ODOO16_REGISTRATION_END
