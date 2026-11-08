/** @odoo-module **/

/**
 * Onboarding tour for the ERP Heritage Approval Workflow.
 *
 * Walks a first-time admin through the two concrete things they need
 * to do before approvals will actually gate posts:
 *
 *   1. Open Approval Policies from the Configuration menu of the
 *      Accounting app and create a per-document-type policy with at
 *      least one rule.
 *   2. Add an approver group + an SLA target on the rule.
 *
 * The tour deliberately does NOT cover the request-side flow
 * (creating + approving + rejecting); that's pure click-through
 * for an end user, not a setup task an admin has to learn.
 *
 * The steps live in the registry.category("web_tour.tours") entry
 * below. Odoo only starts a manual tour that has a web_tour.tour record
 * of the same name (data/approval_tour.xml), so it runs from the URL
 * ?tour=eh_approval_setup_tour or from the Start button under Settings >
 * Technical > Tours. The record is kept out of the automatic onboarding
 * sequence, which would start it on an unrelated screen.
 *
 * It starts on the Approval Requests kanban so the navbar shows the
 * Accounting app (a bare /odoo lands on the first app, usually Discuss).
 * That app is account.menu_finance on Community and the accountant app
 * on Enterprise, so no step names either root: the tour opens the
 * Configuration section, which both layouts carry, and then the
 * Approval Policies entry, which proves the policy screen is reachable
 * from the app the admin is already in. Configuration can be folded into
 * the navbar's "More" menu when the app has many sections; the second
 * selector of that step opens that menu instead, and the policy entry is
 * listed there under the Configuration header. The rule steps wait for
 * the policy list, so the walkthrough cannot run ahead of the screen.
 */

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { markup } from "@odoo/owl";

registry.category("web_tour.tours").add("eh_approval_setup_tour", {
    url: "/odoo/action-eh_account_approval.action_eh_approval_request",
    steps: () => [
        {
            trigger: ".o_main_navbar",
            content: markup(_t(
                "Welcome to the <b>Approval Workflow</b>. " +
                "This walkthrough shows the two setup steps " +
                "you need to do before approvals start gating posts."
            )),
        },
        {
            trigger:
                '.o_menu_sections button[data-menu-xmlid="account.menu_finance_configuration"], ' +
                ".o_menu_sections_more button",
            content: markup(_t(
                "Open the <b>Configuration</b> menu."
            )),
            run: "click",
        },
        {
            trigger:
                '.dropdown-item[data-menu-xmlid="eh_account_approval.menu_eh_approval_policy"]',
            content: markup(_t(
                "Now find the <b>Approval Policies</b> entry under " +
                "Configuration. A policy maps a document type " +
                "(vendor bills, customer invoices, journal entries) " +
                "to a set of approver groups."
            )),
            run: "click",
        },
        {
            trigger: ".o_list_view",
            content: markup(_t(
                "On a policy, add at least one <b>rule</b> with an " +
                "amount band and an ordered list of approver groups. " +
                "The first rule whose band matches the move's amount " +
                "wins; the request walks the group list one signature " +
                "at a time."
            )),
        },
        {
            trigger: ".o_main_navbar",
            content: markup(_t(
                "Set <b>SLA hours</b>, <b>Reminder hours</b>, and an " +
                "<b>Escalation group</b> on the rule for the request " +
                "to track its deadline. The hourly cron sends " +
                "reminders inside the SLA window and forwards a " +
                "breached request to the escalation group once."
            )),
        },
        {
            trigger: ".o_main_navbar",
            content: markup(_t(
                "That's it. Once a policy + rule cover a document, " +
                "users see a <b>Request Approval</b> button on the " +
                "draft form, and posting is blocked until every group " +
                "in the rule has signed off. " +
                "<br/><br/>" +
                "The Approvals menu shows the live pipeline as a " +
                "kanban grouped by state."
            )),
        },
    ],
});
