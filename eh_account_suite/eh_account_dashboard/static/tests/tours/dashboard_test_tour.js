/** @odoo-module **/

/**
 * Browser verification for the Owl dashboard entry point.
 *
 * Test-only asset: proves the Accounting menu action resolves the current
 * user's company-scoped dashboard, renders a real snapshot, and survives a
 * manual refresh round trip.  Stable data-testid selectors keep the tour
 * independent from visual layout and translated labels.
 *
 * ENTER THROUGH THE APP THAT FILES THE MENU, NOT A FIXED APP TILE. On a
 * Community database the dashboard section sits in the finance root
 * (account.menu_finance). Once Enterprise accountant is installed the suite
 * moves every ERP Heritage section into accountant's Accounting app and the
 * emptied finance root is hidden, so a step clicking one fixed tile only
 * ever works in one of the layouts. tests/test_tour.py asks the web
 * client's menu tree which app files this section for the tour user and
 * opens that app the way its home menu tile does; the tour starts in the
 * app's navbar and clicks the section there.
 *
 * KEEP STEP SHAPE MECHANICAL for tools/backport_account.py:
 * one double-quoted trigger per step, with a click run or no run at all.
 * Odoo 20 tours reject empty run functions, so a wait-only step is just
 * its trigger.
 */

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("eh_dashboard_test_tour", {
    url: "/odoo",
    steps: () => [
        {
            trigger: ".o_main_navbar [data-menu-xmlid='eh_account_dashboard.menu_eh_account_dashboard']",
            run: "click",
        },
        {
            trigger: "[data-testid='eh-financial-dashboard'] [data-testid='eh-dashboard-period']",
        },
        {
            trigger: "[data-testid='eh-dashboard-refresh']",
            run: "click",
        },
        {
            trigger: "[data-testid='eh-financial-dashboard'] .eh_dashboard_body",
        },
    ],
});
