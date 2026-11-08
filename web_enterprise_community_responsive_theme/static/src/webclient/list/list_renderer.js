/** @odoo-module **/

// Copyright Badirra / Mahmoud Salheen - All rights reserved.
// Author: Mahmoud Salheen
// License OPL-1 (Odoo Proprietary License v1.0) - see the LICENSE file.

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { ListRenderer } from "@web/views/list/list_renderer";

/**
 * Optional compact row density for list views, matching the tighter row
 * height Enterprise users are used to.
 *
 * The patch adds nothing to the DOM and defines no template handlers - all
 * the renderer template gains is a class and a data attribute the
 * stylesheet keys off. The switch that drives it lives in the user menu
 * (see list_density_service.js).
 *
 * The shared state is read straight off the service: on Odoo 20 it is a
 * proxy(), which is reactive on its own, so no wrapper is needed - and
 * useState no longer exists on this version to wrap it with.
 */
patch(ListRenderer.prototype, {
    setup() {
        super.setup();
        this.badirraState = useService("badirra_list_density").state;
    },
});
