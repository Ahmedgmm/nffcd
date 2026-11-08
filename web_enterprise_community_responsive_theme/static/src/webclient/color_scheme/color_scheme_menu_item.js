/** @odoo-module **/

// Copyright Badirra / Mahmoud Salheen - All rights reserved.
// Author: Mahmoud Salheen
// License OPL-1 (Odoo Proprietary License v1.0) - see the LICENSE file.

import { registry } from "@web/core/registry";
import { getColorScheme, switchColorScheme } from "./color_scheme_service";
import { _t } from "@web/core/l10n/translation";

function toggleColorSchemeItem() {
    return {
        type: "switch",
        id: "badirra.dark_mode",
        description: _t("Dark Mode"),
        // web.UserMenu's own template reads `element.isChecked` (see
        // web/static/src/webclient/user_menu/user_menu.xml), not `checked`.
        // With the wrong property name the switch silently always renders
        // off, even once dark mode is genuinely active.
        isChecked: getColorScheme() === "dark",
        // Read the cookie again here (not a value captured when this menu
        // item object was built) so the toggle is correct even if this
        // function's result is reused across renders instead of being
        // freshly recomputed by the caller.
        callback: () => switchColorScheme(getColorScheme() === "dark" ? "light" : "dark"),
        sequence: 50,
    };
}

registry.category("user_menuitems").add("badirra.dark_mode", toggleColorSchemeItem);
