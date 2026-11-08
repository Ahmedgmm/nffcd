/** @odoo-module **/

/**
 * Automated verification tour for the year-end closing run (IFRS 10/10
 * program, UI layer). Unlike onboarding tours under static/src, this
 * file ships in web.assets_tests only: it never loads for real users and
 * exists solely for HttpCase.start_tour runs in the version matrix.
 *
 * KEEP THE STEP SHAPE MECHANICAL. tools/backport_account.py rewrites test
 * tours for the older series with a line-based transform, so every step
 * must stay in the exact  { trigger: "...", run: "..." }  form below:
 *   - selectors: double-quoted, one per step, prefer [data-menu-xmlid=...]
 *   - actions:   run: "click" | "edit <text>"; a wait-only step has a
 *                trigger and no run key (the tour step schema rejects
 *                an empty run function)
 * The 16 target converts  registry -> tour.register  and  edit -> text;
 * 16/17 targets convert the /odoo url to /web.
 *
 * The run action lands on kanban first (view_mode kanban,list,form), so
 * the create step clicks .o-kanban-button-new (same class on 16-19).
 * The required journal and retained earnings accounts are pre-seeded as
 * ir.default records by tests/test_tour.py, so the tour only edits the
 * two plain date inputs. The run name is sequence-assigned (readonly '/')
 * from the fiscal year-end date and is never edited here. The final step
 * proves the draft saved successfully; compute/post/reverse accounting
 * behavior is exercised by the module's transaction tests, not fabricated
 * in a browser fixture without a seeded ledger.
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

registry.category("web_tour.tours").add("eh_year_end_test_tour", {
    url: "/odoo/action-eh_account_year_end.action_eh_year_end_run",
    steps: () => [
        {
            trigger: "[data-menu-xmlid='account.menu_finance_entries']",
            run: "click",
        },
        {
            trigger: ".dropdown-item[data-menu-xmlid='eh_account_year_end.menu_eh_year_end_run']",
            run: "click",
        },
        {
            trigger: ".o_switch_view.o_list",
            run: "click",
        },
        {
            trigger: ".o_list_button_add",
            run: "click",
        },
        {
            trigger: ".o_field_widget[name='fiscal_year_start'] .o_input",
            run: "click",
        },
        {
            trigger: ".o_field_widget[name='fiscal_year_start'] input",
            run: "fill 01/01/2024",
        },
        {
            trigger: ".o_field_widget[name='fiscal_year_end'] .o_input",
            run: "click",
        },
        {
            trigger: ".o_field_widget[name='fiscal_year_end'] input",
            run: "fill 12/31/2024",
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
