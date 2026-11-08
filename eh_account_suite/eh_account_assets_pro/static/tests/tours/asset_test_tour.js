/** @odoo-module **/

/**
 * Automated verification tour for the fixed asset register (IFRS 10/10
 * program, UI layer). Unlike the onboarding tours under static/src, this
 * file ships in web.assets_tests only: it never loads for real users and
 * exists solely for HttpCase.start_tour runs in the version matrix.
 *
 * KEEP THE STEP SHAPE MECHANICAL. tools/backport_account.py rewrites test
 * tours for the older series with a line-based transform, so every step
 * must stay in the exact  { trigger: "...", run: "..." }  form below:
 *   - selectors: double-quoted, one per step, prefer [data-menu-xmlid=...]
 *   - actions:   run: "click" | "edit <text>", or no run key at all for a
 *                wait-only step (Odoo 20 rejects an empty run function)
 * The 16 target converts  registry -> tour.register  and  edit -> text;
 * 16/17 targets convert the /odoo url to /web.
 *
 * The wrapping Python test pre-creates the "Tour Plant Category" asset
 * category so the required category_id autocomplete has a deterministic
 * match. The asset name is sequence-assigned (readonly '/') and is never
 * edited here. Compute Schedule is draft-safe: it only builds persisted
 * schedule lines and posts nothing, so no accounts are required.
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

registry.category("web_tour.tours").add("eh_assets_test_tour", {
    url: "/odoo/action-eh_account_assets_pro.action_eh_asset",
    steps: () => [
        {
            trigger: "[data-menu-xmlid='account.menu_finance_entries']",
            run: "click",
        },
        {
            trigger: ".dropdown-item[data-menu-xmlid='eh_account_assets_pro.menu_eh_asset_all']",
            run: "click",
        },
        {
            trigger: ".o_list_button_add",
            run: "click",
        },
        {
            trigger: ".o_field_widget[name='code'] input",
            run: "edit TOUR-FA-01",
        },
        {
            trigger: ".o_field_widget[name='category_id'] input",
            run: "edit Tour Plant Category",
        },
        {
            trigger: ".o-autocomplete--dropdown-item a:contains('Tour Plant Category')",
            run: "click",
        },
        {
            trigger: ".o_field_widget[name='acquisition_cost'] input",
            run: "fill 12000.00",
        },
        {
            trigger: ".o_form_button_save",
            run: "click",
        },
        {
            trigger: ".o_form_saved",
        },
        {
            trigger: "button[name='action_compute_schedule']",
            run: "click",
        },
        {
            trigger: ".o_field_widget[name='depreciation_line_ids'] .o_data_row",
        },
    ],
});
