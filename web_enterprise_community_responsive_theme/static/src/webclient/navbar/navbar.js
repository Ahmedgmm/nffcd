/** @odoo-module **/

// Copyright Badirra / Mahmoud Salheen - All rights reserved.
// Author: Mahmoud Salheen
// License OPL-1 (Odoo Proprietary License v1.0) - see the LICENSE file.

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { NavBar } from "@web/webclient/navbar/navbar";
import { onMounted, onPatched } from "@odoo/owl";

patch(NavBar.prototype, {
    setup() {
        super.setup();
        // No useState wrapper: on 20 the service hands back a proxy()
        // object, which is reactive in its own right, so reading
        // hasHomeMenu - here and in navbar.xml's t-att-class - already
        // subscribes this component and re-renders on change. useState does
        // not exist on this version to wrap it with anyway.
        this.badirraHomeMenu = useService("badirra_home_menu");

        // Show the current app's own icon next to its name in the navbar
        // (core Community has no icon there - verified against the real
        // web.NavBar.xml, where .o_menu_brand is a bare text DropdownItem).
        //
        // Done by handing the icon to CSS as a custom property and toggling
        // a marker class, NOT by overriding the template. Two earlier
        // attempts replaced core's .o_menu_brand DropdownItem node via
        // xpath and both white-screened the entire webclient - replacing an
        // OWL *component* node (props/slots and all) is far more fragile
        // than adding an attribute to an element that already exists. The
        // worst case here is simply that no icon shows; the app cannot
        // break, because nothing in the render path is modified.
        // onMounted + onPatched, NOT useEffect. OWL 3 redefined useEffect
        // as `useEffect(fn)` - one argument, auto-tracked - so the second
        // argument this used to pass (the dependency function) is now
        // silently ignored, and the effect instead re-runs whenever a
        // signal it read changes. Reading this.root() subscribes it to the
        // ref, so it re-ran the instant OWL called root.set(header) during
        // mount - at which point .o_menu_brand did not exist yet: the brand
        // is a child DropdownItem component, and children mount after their
        // parent's own block. querySelector returned null, the function
        // returned early, and because it bailed BEFORE reading currentApp
        // it was left subscribed to nothing that ever changes again. One
        // dead run, and the icon could never appear no matter how many
        // apps were opened. Confirmed live: webIconData was present and
        // the CSS resolved a 20x20 background as soon as the property and
        // the class were set by hand, while the element carried neither.
        //
        // The lifecycle hooks fire once the DOM is complete, and again
        // after every re-render - which is also exactly when the current
        // app can have changed, so this covers what the ignored dependency
        // function was for. Re-applying is idempotent: setProperty and
        // classList.toggle both just restate the current answer.
        const applyAppIcon = () => {
            // this.root() , not this.root.el : on Odoo 20 core's NavBar
            // declares "root = signal.ref()" as a class field and the
            // element is read by calling the ref. The .el form is the
            // useRef shape, and useRef does not exist on this version.
            const brandEl = this.root()?.querySelector(".o_menu_brand");
            if (!brandEl) {
                return;
            }
            const icon = this.currentApp?.webIconData;
            if (icon) {
                // CSS.escape isn't applicable to a data: URI; wrapping in
                // quotes keeps any special characters inside it from
                // terminating the url() token.
                brandEl.style.setProperty("--o-badirra-app-icon", `url("${icon}")`);
            } else {
                brandEl.style.removeProperty("--o-badirra-app-icon");
            }
            brandEl.classList.toggle("o_badirra_has_app_icon", Boolean(icon));
        };
        onMounted(applyAppIcon);
        onPatched(applyAppIcon);
    },

    /**
     * Opens the Badirra full-screen app switcher. Called from the button
     * that navbar.xml substitutes in place of the stock apps dropdown.
     */
    onBadirraAppsButtonClick() {
        this.badirraHomeMenu.toggle();
    },
});
