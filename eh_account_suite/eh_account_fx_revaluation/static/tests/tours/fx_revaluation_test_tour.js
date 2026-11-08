/** @odoo-module **/

/**
 * Automated verification tour for the FX revaluation run (IFRS 10/10
 * program, UI layer). Unlike onboarding tours under static/src, this
 * file ships in web.assets_tests only: it never loads for real users and
 * exists solely for HttpCase.start_tour runs in the version matrix.
 *
 * KEEP THE STEP SHAPE MECHANICAL. tools/backport_account.py rewrites test
 * tours for the older series with a line-based transform, so every step
 * must stay in the exact  { trigger: "...", run: "..." }  form below:
 *   - selectors: double-quoted, one per step, prefer [data-menu-xmlid=...]
 *   - actions:   run: "click" | "edit <text>"; a wait-only step omits run
 * The 16 target converts  registry -> tour.register  and  edit -> text;
 * 16/17 targets convert the /odoo url to /web.
 *
 * The tour opens the run action, switches to its list view, creates a
 * draft, fills its description and date, and saves it.
 * The required journal / gain / loss accounts are pre-seeded as
 * ir.default records by tests/test_tour.py, so the tour only edits
 * plain char and date inputs. On 19 a date field holding a value renders
 * a button (o_input o_daterange_start), not an input, until focused, so
 * the tour clicks the field's .o_input first to swap in the real input;
 * on 16/17/18 that same click lands on the plain input and is harmless.
 * The final step waits for the saved-form marker.
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

registry.category("web_tour.tours").add("eh_fx_revaluation_test_tour", {
    url: "/odoo/action-eh_account_fx_revaluation.action_eh_fx_revaluation_run",
    steps: () => [
        {
            trigger: "[data-menu-xmlid='account.menu_finance_entries']",
            run: "click",
        },
        {
            trigger: ".dropdown-item[data-menu-xmlid='eh_account_fx_revaluation.menu_eh_fx_revaluation_run']",
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
            trigger: "[name='description'] input, [name='description'] textarea",
            run: "edit FX tour run",
        },
        {
            trigger: ".o_field_widget[name='revaluation_date'] .o_input",
            run: "click",
        },
        {
            trigger: ".o_field_widget[name='revaluation_date'] input",
            run: "fill 06/15/2026",
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
