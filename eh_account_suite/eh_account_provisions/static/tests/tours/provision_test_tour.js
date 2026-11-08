/** @odoo-module **/

/**
 * Automated verification tour for the provision register (IFRS 10/10
 * program, UI layer). Unlike the onboarding tours under static/src, this
 * file ships in web.assets_tests only: it never loads for real users and
 * exists solely for HttpCase.start_tour runs in the version matrix.
 *
 * KEEP THE STEP SHAPE MECHANICAL. tools/backport_account.py rewrites test
 * tours for the older series with a line-based transform, so every step
 * must stay in the exact  { trigger: "...", run: "..." }  form below:
 *   - selectors: double-quoted, one per step, prefer [data-menu-xmlid=...]
 *   - actions:   run: "click" | "edit <text>"; a wait-only step has
 *                a trigger and no run key (Odoo 20 rejects an empty
 *                run function in its step schema)
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
 *
 * TYPE OVER A PRE-FILLED INPUT WITH fill, NOT edit. hoot's edit helper
 * begins by clearing the input with a Control+A select all, and the web
 * client reads Control as the hotkey overlay modifier on this platform, so
 * that shortcut is dispatched as the alt+a hotkey and moves focus to any
 * visible element declaring data-hotkey="a". The rest of the keystrokes
 * then land on that element and the field silently keeps its old value.
 * Numeric and date inputs already select their whole content on focus
 * (useNumpadDecimal and the datetime picker both do it), so fill types the
 * same characters over that selection and needs no clear. Keep edit for
 * inputs that are empty when the tour reaches them.
 */

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("eh_provisions_test_tour", {
    url: "/odoo/action-eh_account_provisions.action_eh_provision",
    steps: () => [
        {
            trigger: "[data-menu-xmlid='account.menu_finance_entries']",
            run: "click",
        },
        {
            trigger: ".dropdown-item[data-menu-xmlid='eh_account_provisions.menu_eh_provision']",
            run: "click",
        },
        {
            trigger: ".o_list_button_add",
            run: "click",
        },
        {
            trigger: ".o_field_widget[name='best_estimate'] input",
            run: "fill 1000.00",
        },
        {
            trigger: ".o_field_widget[name='action_accounting_date'] input",
            run: "fill 2026-01-01",
        },
        {
            trigger: ".o_form_button_save",
            run: "click",
        },
        {
            trigger: ".o_form_saved",
        },
    ],
});
