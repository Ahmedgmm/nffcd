/** @odoo-module **/

import { Component, onWillStart, proxy } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class CitadelAuthorityDashboard extends Component {
    static template = "citadel_authority.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({ loading: true, data: { blocks: [], totals: {} }, blockKey: false, flowIndex: 0 });
        onWillStart(async () => {
            this.state.data = await this.orm.call("citadel.authority.dashboard", "get_dashboard_data", []);
            this.state.blockKey = this.state.data.blocks[0]?.key || false;
            this.state.loading = false;
        });
    }

    get block() {
        return this.state.data.blocks.find((block) => block.key === this.state.blockKey);
    }

    get flow() {
        return this.block?.flows[this.state.flowIndex] || false;
    }

    selectBlock(key) {
        this.state.blockKey = key;
        this.state.flowIndex = 0;
    }

    onFlowChange(event) {
        this.state.flowIndex = Number(event.target.value);
    }

    openRequests(documentType = false, waiting = false) {
        const domain = documentType ? [["document_type", "=", documentType]] : [];
        if (waiting) domain.push(["state", "=", "pending"], ["can_approve", "=", true]);
        this.action.doAction({
            type: "ir.actions.act_window", name: "طلبات الصلاحيات", res_model: "citadel.authority.request",
            views: [[false, "list"], [false, "form"]], domain,
        });
    }

    editFlow() {
        if (!this.flow || !this.state.data.is_manager) return;
        this.action.doAction({
            type: "ir.actions.act_window", res_model: "citadel.authority.policy", res_id: this.flow.id,
            views: [[false, "form"]], target: "new",
        });
    }
}

registry.category("actions").add("citadel_authority.dashboard", CitadelAuthorityDashboard);

