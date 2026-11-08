/** @odoo-module **/
// Copyright (C) 2026 ERP Heritage.
import { describe, expect, test } from "@odoo/hoot";
import { EhDynamicReportViewer } from "@eh_account_dynamic_reports/components/dynamic_report/dynamic_report";

describe("eh dynamic report - ledger picker scope", () => {
    test("saved view reloads its company ledgers before refreshing", async () => {
        const calls = [];
        const viewer = {
            state: {
                reportId: 1,
                options: { company_ids: [1], ledger_scope: "statutory", ledger_group_ids: [] },
                choices: { ledgers: [{ id: 11, name: "Company one adjustments" }] },
            },
            orm: { async call(model, method, args) {
                calls.push(method);
                if (method === "load_options") {
                    return { company_ids: [2], ledger_scope: "selected", ledger_group_ids: [22] };
                }
                expect(args[1]).toEqual([2]);
                return [{ id: 22, name: "Company two adjustments" }];
            } },
            savedViewOptionDefaults: EhDynamicReportViewer.prototype.savedViewOptionDefaults,
            loadLedgerChoices: EhDynamicReportViewer.prototype.loadLedgerChoices,
            refresh() { calls.push("refresh"); },
            notification: { add() { throw new Error("Unexpected saved-view failure"); } },
        };
        await EhDynamicReportViewer.prototype.onSavedViewChange.call(viewer, { target: { value: "8" } });
        expect(viewer.state.options.company_ids).toEqual([2]);
        expect(viewer.state.options.ledger_group_ids).toEqual([22]);
        expect(viewer.state.choices.ledgers.map((ledger) => ledger.id)).toEqual([22]);
        expect(calls).toEqual(["load_options", "get_ledger_choices", "refresh"]);
    });

    test("late previous-company response cannot replace current ledger choices", async () => {
        const pending = [];
        const viewer = {
            state: { reportId: 1, options: { company_ids: [1] }, choices: { ledgers: [] } },
            orm: { call() { return new Promise((resolve) => pending.push(resolve)); } },
        };
        const first = EhDynamicReportViewer.prototype.loadLedgerChoices.call(viewer);
        viewer.state.options.company_ids = [2];
        const second = EhDynamicReportViewer.prototype.loadLedgerChoices.call(viewer);
        pending[1]([{ id: 22 }]);
        expect(await second).toBe(true);
        pending[0]([{ id: 11 }]);
        expect(await first).toBe(false);
        expect(viewer.state.choices.ledgers.map((ledger) => ledger.id)).toEqual([22]);
    });
});
