/** @odoo-module **/

// Copyright Badirra / Mahmoud Salheen - All rights reserved.
// Author: Mahmoud Salheen
// License OPL-1 (Odoo Proprietary License v1.0) - see the LICENSE file.

import { useService } from "@web/core/utils/hooks";
import { useSortable } from "@web/core/utils/sortable_owl";
import { browser } from "@web/core/browser/browser";
// Odoo 20 ships an OWL whose reactivity is signal-based: useState and
// useRef are GONE from the library entirely - verified, zero occurrences in
// owl.js and zero uses across addons/web. proxy() replaces useState, and a
// ref is a `signal.ref()` CLASS FIELD read by calling it, not a hook
// returning an object with .el.
import { Component, onMounted, onWillUnmount, proxy, signal, t } from "@odoo/owl";

const ORDER_STORAGE_KEY = "badirra_homemenu_order";

/**
 * BadirraHomeMenu - full-screen grid app switcher.
 *
 * Mounted by the "badirra_home_menu" action (see home_menu_service.js) as a
 * real controller in the action stack, the same way Odoo Enterprise's own
 * home menu works: opening it is a normal navigation, and closing it is a
 * normal "go back to the previous breadcrumb" restore.
 *
 * App tiles are drag-reorderable (matching ica_web_responsive's home menu),
 * with the order kept in localStorage rather than a server-side user
 * setting: persisting it server-side would need a new field on
 * res.users.settings, which lives in the "mail" module - adding that as a
 * hard dependency just for this would be a heavy ask for a free theme.
 * Trade-off: the custom order is per-browser, not synced across devices.
 */
export class BadirraHomeMenu extends Component {
    static template = "web_enterprise_community_responsive_theme.HomeMenu";

    // Class fields, not setup() calls: this is how Odoo 20 declares refs
    // (see any core component, e.g. core/autocomplete/autocomplete.js).
    // The template binds them with t-ref="this.searchRef" and the element
    // is read by CALLING the ref - this.searchRef() - rather than .el.
    searchRef = signal.ref();
    gridRef = signal.ref();

    // A SIGNAL, not a property on the proxy below. OWL 3's t-model binds
    // two ways, so it requires something it can write back INTO: given a
    // plain reactive property it throws "expression should evaluate to a
    // function with a 'set' method". A signal is read by calling it and
    // written with .set(), which is exactly that contract - the same shape
    // core's emoji picker uses for its own search box.
    query = signal("", { type: t.string() });

    setup() {
        this.menuService = useService("menu");
        this.homeMenu = useService("badirra_home_menu");
        // The saved order stays a proxy: the template reads it but never
        // binds it with t-model, so it needs reactivity, not a setter.
        this.state = proxy({ order: this.loadOrder() });

        useSortable({
            enable: () => !this.query().trim(),
            ref: this.gridRef,
            elements: ".o_badirra_app_icon",
            cursor: "grabbing",
            delay: 150,
            tolerance: 10,
            onDrop: ({ element, previous }) => this.onAppDrop(element, previous),
        });

        this.onKeydown = this.onKeydown.bind(this);
        onMounted(() => {
            document.addEventListener("keydown", this.onKeydown);
            this.searchRef()?.focus();
        });
        onWillUnmount(() => document.removeEventListener("keydown", this.onKeydown));
    }

    get apps() {
        const apps = this.menuService.getApps();
        const query = this.query().trim().toLowerCase();
        if (query) {
            return apps
                .filter((app) => app.name.toLowerCase().includes(query))
                .sort((a, b) => a.name.localeCompare(b.name));
        }
        return this.applyOrder(apps);
    }

    appKey(app) {
        return app.xmlid || String(app.id);
    }

    loadOrder() {
        try {
            const stored = JSON.parse(browser.localStorage.getItem(ORDER_STORAGE_KEY) || "[]");
            return Array.isArray(stored) ? stored : [];
        } catch {
            return [];
        }
    }

    saveOrder(order) {
        this.state.order = order;
        browser.localStorage.setItem(ORDER_STORAGE_KEY, JSON.stringify(order));
    }

    // Apps the user has never manually reordered still default to
    // alphabetical; any app not (yet) present in a saved order - e.g. one
    // just installed - is appended alphabetically after the ordered ones
    // rather than dropped or jumbled in.
    applyOrder(apps) {
        if (!this.state.order.length) {
            return [...apps].sort((a, b) => a.name.localeCompare(b.name));
        }
        const byKey = new Map(apps.map((app) => [this.appKey(app), app]));
        const ordered = [];
        for (const key of this.state.order) {
            const app = byKey.get(key);
            if (app) {
                ordered.push(app);
                byKey.delete(key);
            }
        }
        const rest = [...byKey.values()].sort((a, b) => a.name.localeCompare(b.name));
        return [...ordered, ...rest];
    }

    onAppDrop(element, previous) {
        const order = this.apps.map((app) => this.appKey(app));
        const draggedKey = element.dataset.appKey;
        const draggedIndex = order.indexOf(draggedKey);
        if (draggedIndex === -1) {
            return;
        }
        order.splice(draggedIndex, 1);
        if (previous) {
            const previousIndex = order.indexOf(previous.dataset.appKey);
            order.splice(previousIndex + 1, 0, draggedKey);
        } else {
            order.unshift(draggedKey);
        }
        this.saveOrder(order);
    }

    onAppClick(app) {
        this.menuService.selectMenu(app);
    }

    onKeydown(ev) {
        if (ev.key === "Escape") {
            this.homeMenu.close();
        }
    }
}
