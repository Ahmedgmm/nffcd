/** @odoo-module **/

/**
 * Automated verification tour for the IAS 19 benefit plan register. Unlike
 * onboarding tours under static/src, this file
 * ships in web.assets_tests only: it never loads for real users and exists
 * solely for HttpCase.start_tour runs in the version matrix.
 *
 * KEEP THE STEP SHAPE MECHANICAL. tools/backport_account.py rewrites test
 * tours for the older series with a line-based transform, so every step
 * acting steps must stay in the exact { trigger: "...", run: "..." } form;
 * a final assertion-only step may omit ``run``:
 *   - selectors: double-quoted, one per step, prefer [data-menu-xmlid=...]
 *   - actions:   run: "click" | "edit <text>", or no run key for a step
 *                that only waits for its trigger (Odoo 20 rejects an empty
 *                run function)
 * The 16 target converts  registry -> tour.register  and  edit -> text;
 * 16/17 targets convert the /odoo url to /web.
 *
 * ENTER THROUGH THE ACTION, NOT AN APP TILE. The core finance sections
 * (Accounting, Reporting, Configuration) hang off the Invoicing root menu
 * on a plain Community database, and the accountant module reparents them
 * under its own Accounting root, so a step clicking one fixed app tile only
 * ever works on one of the two layouts. Opening the record action puts the
 * web client in whichever root owns this menu; the navbar steps below then
 * still prove the menu is filed under the finance section and opens the
 * list. tests/test_tour.py asserts the menu-to-action binding and the
 * section ancestry in Python, where no layout can hide it.
 */

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("eh_employee_benefits_test_tour", {
    url: "/odoo/action-eh_account_employee_benefits.action_eh_benefit_plan",
    steps: () => [
        {
            trigger: "[data-menu-xmlid='account.menu_finance_entries']",
            run: "click",
        },
        {
            trigger: ".dropdown-item[data-menu-xmlid='eh_account_employee_benefits.menu_eh_benefit_plan']",
            run: "click",
        },
        {
            trigger: ".o_list_button_add",
            run: "click",
        },
        {
            trigger: ".o_field_widget[name='name'] input",
            run: "edit Group Pension Plan",
        },
        {
            trigger: ".o_field_widget[name='country_note'] input",
            run: "edit Head office jurisdiction",
        },
        {
            trigger: ".o_form_button_save",
            run: "click",
        },
        {
            trigger: ".o_form_saved",
        },
        {
            trigger: "button[name='action_activate']",
            run: "click",
        },
        {
            trigger: "button[name='action_close']",
        },
    ],
});
