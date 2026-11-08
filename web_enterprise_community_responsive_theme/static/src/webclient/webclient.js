/** @odoo-module **/

// Copyright Badirra / Mahmoud Salheen - All rights reserved.
// Author: Mahmoud Salheen
// License OPL-1 (Odoo Proprietary License v1.0) - see the LICENSE file.

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { WebClient } from "@web/webclient/webclient";

/**
 * Community's WebClient falls back to auto-selecting the first app whenever
 * there is no action/state to restore (fresh login, "/odoo" with no route).
 * Enterprise instead lands on the full-screen app switcher in that case.
 * This is that same behavior: open the Badirra home menu instead of
 * silently jumping into whatever the first menu happens to be.
 */
patch(WebClient.prototype, {
    setup() {
        super.setup();
        this.badirraHomeMenu = useService("badirra_home_menu");
    },

    _loadDefaultApp() {
        return this.badirraHomeMenu.open();
    },
});
