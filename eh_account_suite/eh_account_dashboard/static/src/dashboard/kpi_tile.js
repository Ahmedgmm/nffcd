/** @odoo-module **/

/**
 * Single reactive KPI tile.
 *
 * Renders one card with: caption, primary value (already-formatted by
 * the parent), optional caption secondary text, optional drill-down
 * button. The parent passes a `statusClass` that maps to the suite
 * palette (eh_dash_status_*). This is a pure presentational component;
 * it owns no state and never calls RPC.
 *
 * Why a separate component instead of inlining in the parent template:
 *   - the layout repeats 8+ times, so the duplication is real;
 *   - drill-down semantics are uniform (one button name -> one action);
 *   - keeps the parent template focused on layout, not per-tile markup.
 */

import { Component, t, useProps } from "@odoo/owl";

export class KpiTile extends Component {
    static template = "eh_account_dashboard.KpiTile";
    props = useProps({
        caption: t.string(),
        value: t.or([t.string(), t.number()]).optional(),
        secondary: t.string().optional(),
        statusClass: t.string().optional("eh_dash_status_neutral"),
        // Material Symbols name rendered through the "oi" icon font.
        icon: t.string().optional("radio_button_unchecked"),
        drilldownLabel: t.string().optional(),
        onDrilldown: t.function().optional(),
        // Optional prior-period comparison. When delta is set, the tile
        // renders a small badge with the absolute change and (when pct
        // is non-null) the percentage change, colour-coded by sign and
        // by whether higher is better.
        delta: t.or([t.string(), t.number()]).optional(),
        deltaPct: t.or([t.string(), t.number()]).optional(),
        deltaLabel: t.string().optional(),
        higherIsBetter: t.boolean().optional(true),
    });

    get deltaClass() {
        if (this.props.delta === undefined || this.props.delta === null) {
            return "";
        }
        const v = Number(this.props.delta);
        if (v === 0) {
            return "eh_dash_delta_flat";
        }
        const positive = v > 0;
        const good = positive === this.props.higherIsBetter;
        return good ? "eh_dash_delta_up" : "eh_dash_delta_down";
    }

    get deltaArrow() {
        if (this.props.delta === undefined || this.props.delta === null) {
            return "";
        }
        const v = Number(this.props.delta);
        if (v === 0) {
            return "remove";
        }
        return v > 0 ? "arrow_upward" : "arrow_downward";
    }
}
