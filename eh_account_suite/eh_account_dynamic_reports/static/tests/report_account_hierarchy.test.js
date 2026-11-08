/** @odoo-module **/
// Copyright (C) 2026 ERP Heritage.

import { describe, expect, test } from "@odoo/hoot";
import { contains, mockService, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { EhDynamicReportViewer } from "@eh_account_dynamic_reports/components/dynamic_report/dynamic_report";

defineMailModels();

// Mount the production template and option handlers without financial RPCs.
// The handler capability is supplied exactly as bootstrap's report read does.
class HierarchyViewer extends EhDynamicReportViewer {
    async bootstrap() {
        this.state.reportId = 7;
        this.state.reportName = "Hierarchy report test";
        this.state.supportsAccountHierarchy = this.props.action.context.hierarchy;
        this.state.loading = false;
        this.renderedOptions = [];
    }

    async refresh() {
        this.normalizeCapabilityOptions();
        this.renderedOptions.push(JSON.parse(JSON.stringify(this.state.options)));
    }

    async loadLedgerChoices() {
        return true;
    }

    async loadSavedViews() {}
}

async function mountViewer(code = "trial_balance", hierarchy = true, call = async () => ({})) {
    mockService("orm", { call });
    mockService("action", { doAction() {} });
    return mountWithCleanup(HierarchyViewer, {
        props: { action: { context: { report_code: code, hierarchy } } },
    });
}

describe("eh dynamic report - native account hierarchy", () => {
    test("visible selector switches layouts without losing the financial scope", async () => {
        const viewer = await mountViewer();
        expect(".eh_dr_account_hierarchy").toHaveCount(1);
        expect(".eh_dr_account_hierarchy").toHaveValue("hierarchy");
        Object.assign(viewer.state.options, {
            company_ids: [10], ledger_scope: "selected", ledger_group_ids: [20],
            account_ids: [30], comparison: "previous_year", unfold_all: true,
            unfolded_lines: ["group-40"],
        });
        viewer.state.expandedLines = ["group-40"];
        viewer.state.childLines = { "account-30": { lines: [{ id: "aml-1" }] } };
        await contains(".eh_dr_account_hierarchy").select("flat");
        expect(viewer.renderedOptions.at(-1).hierarchical_groups).toBe(false);
        expect(viewer.state.options.company_ids).toEqual([10]);
        expect(viewer.state.options.ledger_group_ids).toEqual([20]);
        expect(viewer.state.options.account_ids).toEqual([30]);
        expect(viewer.state.options.comparison).toBe("previous_year");
        expect(viewer.state.options.unfold_all).toBe(false);
        expect(viewer.state.options.unfolded_lines).toEqual([]);
        expect(viewer.state.expandedLines).toEqual([]);
        expect(viewer.state.childLines).toEqual({});
        await contains(".eh_dr_account_hierarchy").select("hierarchy");
        expect(viewer.renderedOptions.at(-1).hierarchical_groups).toBe(true);
        expect(viewer.renderedOptions).toHaveLength(2);
    });

    for (const code of ["general_ledger", "custom_trading_report", "partner_ledger"]) {
        test(`${code} keeps its own row structure without a parent-account control`, async () => {
            const viewer = await mountViewer(code, false);
            expect(".eh_dr_account_hierarchy").toHaveCount(0);
            viewer.state.options.hierarchical_groups = false;
            viewer.normalizeCapabilityOptions();
            expect("hierarchical_groups" in viewer.state.options).toBe(false);
            viewer.onAccountHierarchyChange({ target: { value: "hierarchy" } });
            expect(viewer.renderedOptions).toHaveLength(0);
        });
    }

    test("capability is authoritative even when the code normally supports hierarchy", async () => {
        await mountViewer("trial_balance", false);
        expect(".eh_dr_account_hierarchy").toHaveCount(0);
    });

    test("flat layout reaches PDF, XLSX and saved views as an explicit false", async () => {
        const calls = [];
        const viewer = await mountViewer("profit_and_loss", true, async (model, method, args) => {
            calls.push({ method, args: JSON.parse(JSON.stringify(args)) });
            return method === "save_view" ? 9 : {};
        });
        await contains(".eh_dr_account_hierarchy").select("flat");
        await viewer.onPrintPdf();
        await viewer.onExportXlsx();
        viewer.onSaveCurrentView();
        viewer.state.savedViewName = "Flat management accounts";
        await viewer.onConfirmSaveCurrentView();
        expect(calls.map(({ method }) => method)).toEqual([
            "export_pdf_attachment", "export_xlsx_attachment", "save_view",
        ]);
        expect(calls[0].args[1].hierarchical_groups).toBe(false);
        expect(calls[1].args[1].hierarchical_groups).toBe(false);
        expect(calls[2].args[2].hierarchical_groups).toBe(false);
    });

    test("saved flat and legacy hierarchy views restore the visible control and export choice", async () => {
        const exports = [];
        const viewer = await mountViewer("balance_sheet", true, async (model, method, args) => {
            if (method === "load_options") {
                return args[0][0] === 8 ? { hierarchical_groups: false } : {};
            }
            exports.push(JSON.parse(JSON.stringify(args[1])));
            return {};
        });
        await viewer.onSavedViewChange({ target: { value: "8" } });
        await viewer.onPrintPdf();
        expect(exports[0].hierarchical_groups).toBe(false);
        expect(viewer.renderedOptions.at(-1).hierarchical_groups).toBe(false);
        await viewer.onSavedViewChange({ target: { value: "9" } });
        await viewer.onExportXlsx();
        expect(exports[1].hierarchical_groups).toBe(true);
        expect(viewer.renderedOptions.at(-1).hierarchical_groups).toBe(true);
    });

    test("unsupported saved hierarchy values do not reach report exports", async () => {
        let exported;
        const viewer = await mountViewer("general_ledger", false, async (model, method, args) => {
            if (method === "load_options") return { hierarchical_groups: false };
            exported = args[1];
            return {};
        });
        await viewer.onSavedViewChange({ target: { value: "8" } });
        await viewer.onExportXlsx();
        expect("hierarchical_groups" in exported).toBe(false);
    });

    test("invalid and unchanged layout inputs do not refresh or change scope", async () => {
        const viewer = await mountViewer();
        viewer.onAccountHierarchyChange({ target: { value: "flat-ish" } });
        viewer.onAccountHierarchyChange({ target: { value: "hierarchy" } });
        expect(viewer.state.options.hierarchical_groups).toBe(true);
        expect(viewer.renderedOptions).toHaveLength(0);
    });
});
