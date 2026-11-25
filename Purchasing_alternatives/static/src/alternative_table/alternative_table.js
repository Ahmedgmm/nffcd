/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { Component, onWillStart, proxy, useProps } from "@odoo/owl";

export class PurchaseAlternativeTable extends Component {
    static template = "Purchasing_alternatives.AlternativeTable";
    static components = { ControlPanel };
    props = useProps({ ...standardActionServiceProps });

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = proxy({
            loading: true,
            data: {},
            addingVendor: false,
        });
        this.comparisonId = this.props.action.params.comparison_id;
        onWillStart(async () => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.data = await this.orm.call(
            "purchase.alternative.comparison",
            "get_table_data",
            [[this.comparisonId]]
        );
        this.state.loading = false;
    }

    formatNumber(value) {
        return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
    }

    formatMoney(value) {
        const currency = this.state.data.order ? this.state.data.order.currency : "";
        return `${this.formatNumber(value)} ${currency || ""}`.trim();
    }

    cellClass(cell) {
        const classes = ["o_alt_offer_cell"];
        if (cell.is_lowest_price) {
            classes.push("o_alt_lowest_price");
        }
        if (Number(cell.offered_qty || 0) > 0) {
            classes.push("o_alt_has_qty");
        }
        return classes.join(" ");
    }

    rowClass(row) {
        return `o_alt_row o_alt_row_${row.allocation_state || "empty"}`;
    }

    allocationLabel(row) {
        const labels = {
            empty: _t("No split"),
            partial: _t("Partial split"),
            complete: _t("Complete"),
            over: _t("Over allocated"),
        };
        return labels[row.allocation_state] || labels.empty;
    }

    allocationIcon(row) {
        const icons = {
            empty: "fa-circle-o",
            partial: "fa-adjust",
            complete: "fa-check-circle",
            over: "fa-exclamation-triangle",
        };
        return icons[row.allocation_state] || icons.empty;
    }

    selectInput(ev) {
        ev.target.select();
    }

    focusPriceInput(index) {
        const inputs = document.querySelectorAll(".o_alt_price_input");
        const target = inputs[index];
        if (target) {
            target.focus();
            target.select();
        }
    }

    onPriceKeydown(cell, ev) {
        const inputs = Array.from(document.querySelectorAll(".o_alt_price_input"));
        const index = inputs.indexOf(ev.target);
        if (index < 0) {
            return;
        }
        const vendorCount = (this.state.data.vendors || []).length || 1;
        let nextIndex = false;
        if (ev.key === "Tab") {
            nextIndex = index + (ev.shiftKey ? -1 : 1);
        } else if (ev.key === "ArrowRight") {
            nextIndex = index + 1;
        } else if (ev.key === "ArrowLeft") {
            nextIndex = index - 1;
        } else if (ev.key === "ArrowDown") {
            nextIndex = index + vendorCount;
        } else if (ev.key === "ArrowUp") {
            nextIndex = index - vendorCount;
        }
        if (nextIndex === false) {
            return;
        }
        if (nextIndex < 0 || nextIndex >= inputs.length) {
            return;
        }
        ev.preventDefault();
        this.focusPriceInput(nextIndex);
    }

    async addVendor() {
        await this.orm.call("purchase.alternative.comparison", "action_add_vendor", [[this.comparisonId]]);
        await this.load();
    }

    async updateCell(cell, field, ev) {
        const value = ev.target.value;
        this.state.data = await this.orm.call(
            "purchase.alternative.comparison",
            "action_update_cell",
            [[this.comparisonId], cell.id, { [field]: value }]
        );
    }

    async updateVendor(vendor, field, ev) {
        const value = ev.target.value;
        this.state.data = await this.orm.call(
            "purchase.alternative.comparison",
            "action_update_vendor",
            [[this.comparisonId], vendor.id, { [field]: value }]
        );
    }

    async updateTechnicalOpinion(ev) {
        this.state.data = await this.orm.call(
            "purchase.alternative.comparison",
            "action_update_technical_opinion",
            [[this.comparisonId], ev.target.value]
        );
    }

    get authority() {
        return this.state.data.authority || {};
    }

    isApprovedMain(vendor) {
        const auth = this.authority;
        return this.state.data.state === 'review' && auth.approved && auth.decision_vendor_id === vendor.id;
    }

    isApprovedSplit() {
        const auth = this.authority;
        return this.state.data.state === 'review' && auth.approved && !auth.decision_vendor_id && Boolean(auth.decision);
    }

    async applyMain(vendor) {
        if (!this.isApprovedMain(vendor)) {
            this.state.data = await this.orm.call(
                "purchase.alternative.comparison",
                "action_submit_main_decision",
                [[this.comparisonId], vendor.id]
            );
            this.notification.add(_t("Decision sent to the committee for approval."), { type: "info" });
            return;
        }
        this.state.data = await this.orm.call(
            "purchase.alternative.comparison",
            "action_apply_main_vendor",
            [[this.comparisonId], vendor.id]
        );
        this.notification.add(_t("Original RFQ updated."), { type: "success" });
    }

    async approveDecision() {
        await this.orm.call("purchase.alternative.comparison", "action_citadel_approve", [[this.comparisonId]]);
        await this.load();
        this.notification.add(_t("Your approval was recorded."), { type: "success" });
    }

    async withdrawDecision() {
        this.state.data = await this.orm.call(
            "purchase.alternative.comparison",
            "action_reset_committee_decision",
            [[this.comparisonId]]
        );
    }

    async callAction(method) {
        const action = await this.orm.call("purchase.alternative.comparison", method, [[this.comparisonId]]);
        await this.action.doAction(action, { onClose: () => this.load() });
    }

    async createPO(vendor) {
        const action = await this.orm.call(
            "purchase.alternative.comparison",
            "action_create_po_for_vendor",
            [[this.comparisonId], vendor.id]
        );
        await this.action.doAction(action);
    }

    async createSplitPOs() {
        if (!this.isApprovedSplit()) {
            this.state.data = await this.orm.call(
                "purchase.alternative.comparison",
                "action_submit_split_decision",
                [[this.comparisonId]]
            );
            this.notification.add(_t("Split decision sent to the committee for approval."), { type: "info" });
            return;
        }
        const action = await this.orm.call(
            "purchase.alternative.comparison",
            "action_create_split_pos",
            [[this.comparisonId]]
        );
        this.notification.add(_t("Split RFQs created by vendor."), { type: "success" });
        await this.action.doAction(action);
    }

    openOriginal() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "purchase.order",
            res_id: this.state.data.order.id,
            view_mode: "form",
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("purchase_alternative_table", PurchaseAlternativeTable);
