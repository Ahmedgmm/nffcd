/** @odoo-module **/

// Copyright Badirra / Mahmoud Salheen - All rights reserved.
// Author: Mahmoud Salheen
// License OPL-1 (Odoo Proprietary License v1.0) - see the LICENSE file.

import { registry } from "@web/core/registry";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { proxy } from "@odoo/owl";

const STORAGE_KEY = "badirra_list_density";

/**
 * Compact-density preference for list views.
 *
 * The switch lives in the user menu, and the renderer template gains
 * nothing but a class and a data attribute. Two separate faults on the
 * earlier branches are the reason it is built this way rather than as a
 * button inside the list:
 *
 *   - the injected button was absolutely positioned at top:-2.5rem, i.e.
 *     floating ABOVE the list. On a list view that is where the control
 *     panel's pager and view switcher sit; inside a one2many it is the
 *     field above the sub-list. With a z-index it swallowed the clicks in
 *     both, in every list, in every module;
 *   - and the xpath that placed it, expr=".", selects the <t t-name>
 *     wrapper rather than the content root, so position="inside" appended
 *     a SECOND root-level child - which an OWL template may not have.
 *
 * ica_web_responsive injects nothing positioned into list views and keeps
 * its own settings in the user menu; that is the pattern followed here.
 *
 * The state is a proxy() so flipping the switch re-renders every list
 * currently mounted. It is a per-browser display preference in
 * localStorage - it never touches record data or the server.
 */
const listDensityService = {
    start() {
        const state = proxy({
            dense: browser.localStorage.getItem(STORAGE_KEY) === "1",
        });
        return {
            get dense() {
                return state.dense;
            },
            // Handed out so consumers can read the proxied object itself;
            // reading through the getter above would not subscribe them.
            state,
            toggle() {
                state.dense = !state.dense;
                browser.localStorage.setItem(STORAGE_KEY, state.dense ? "1" : "0");
            },
        };
    },
};

registry.category("services").add("badirra_list_density", listDensityService);

function listDensityItem(env) {
    const service = env.services.badirra_list_density;
    return {
        type: "switch",
        id: "badirra.list_density",
        description: _t("Compact Lists"),
        isChecked: service.dense,
        callback: () => service.toggle(),
        sequence: 51,
    };
}

registry.category("user_menuitems").add("badirra.list_density", listDensityItem);
