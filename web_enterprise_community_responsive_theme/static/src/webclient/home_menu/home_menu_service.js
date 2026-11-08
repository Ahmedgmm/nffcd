/** @odoo-module **/

// Copyright Badirra / Mahmoud Salheen - All rights reserved.
// Author: Mahmoud Salheen
// License OPL-1 (Odoo Proprietary License v1.0) - see the LICENSE file.

import { registry } from "@web/core/registry";
// Odoo 20 replaced the monolithic action_service with a plugin
// architecture: action_service.js no longer exists, and both of these moved
// to action_plugin.js. The actions registry and the action service itself
// are unchanged - a client action is still a Component registered under a
// tag, and doAction/restore still work the same way.
import {
    ControllerNotFoundError,
    standardActionServiceProps,
} from "@web/webclient/actions/action_plugin";
import { BadirraHomeMenu } from "./home_menu";
// reactive() is no longer an OWL export on 20 - what remains under that
// name is a local helper in @web/core/utils/reactive. proxy() is the
// library primitive that replaces it, and it is what core uses for shared
// mutable state.
import { Component, onWillUnmount, proxy, useProps } from "@odoo/owl";

/**
 * The full-screen app switcher is a genuine action, exactly like
 * Enterprise's own home menu: opening it pushes it onto the action/
 * breadcrumb stack instead of drawing an overlay on top of whatever view
 * is currently shown. Closing it means going back to the controller that
 * was there before, via the action service's own restore().
 *
 * The action is registered under the literal tag "menu" on purpose, not
 * something namespaced like "badirra_home_menu": Odoo's own core code
 * special-cases that exact string - 
 *   - router.js's stateToUrl() skips writing an action path segment onto
 *     the URL when the current action is "menu", which is the entire
 *     reason Enterprise's/ica_web_responsive's home menu shows a clean
 *     "/odoo" URL instead of "/odoo/menu";
 *   - action_service.js's _getBreadcrumbs()/_loadBreadcrumbs() both
 *     explicitly filter out any controller whose action tag is "menu".
 * Using any other tag silently loses both of those, which is exactly the
 * "URL looks wrong" symptom this was fixed for.
 */
const HOME_MENU_ACTION_TAG = "menu";

// The service web_enterprise registers for its own home menu. Only present
// on an Enterprise install; used to hand the job over rather than compete
// with it - see the comment in start().
const NATIVE_HOME_MENU_SERVICE = "home_menu";
const NATIVE_HOME_MENU_EVENT = "HOME-MENU:TOGGLED";

const homeMenuService = {
    dependencies: ["action"],
    start(env) {
        const state = proxy({ hasHomeMenu: false, hasBackgroundAction: false });

        // On ENTERPRISE this action tag is already spoken for:
        // web_enterprise's home_menu_service.js registers "menu" too. The
        // registry throws DuplicatedKeyError on a second add without force,
        // and both registrations happen inside a service start(), so ONE of
        // the two services is guaranteed to blow up. A failed service start
        // leaves the webclient unmounted: a completely blank backend with
        // NOTHING in the server log, because the failure is entirely
        // client-side.
        //
        // Detection is deliberately NOT registry.category("actions")
        // .contains("menu"). That would only be true if their service
        // happened to start before ours, and service start order is not
        // ours to rely on - if we won the race we would register first and
        // THEIR add would throw instead, same blank screen, now harder to
        // read. The SERVICE registration is the stable signal: it runs at
        // module load, long before any start(), so this answer is the same
        // no matter who boots first.
        //
        // Deferring rather than forcing. This theme exists to bring an
        // Enterprise-grade home menu to COMMUNITY; where the real one is
        // already installed it is the better-integrated component - it
        // keeps menu_id in the URL, holds a Mutex against concurrent
        // toggles, and the rest of web_enterprise reads its service. So on
        // Enterprise our button drives theirs, and everything else in the
        // theme - navbar, dark mode, views, login - still applies.
        const nativeHomeMenu = registry
            .category("services")
            .contains(NATIVE_HOME_MENU_SERVICE);

        class BadirraHomeMenuAction extends Component {
            static template = "web_enterprise_community_responsive_theme.HomeMenuAction";
            static components = { BadirraHomeMenu };
            // useProps, NOT "static props": OWL 3 ignores a static props
            // declaration and throws on it outright -
            // "defines a static props or defaultProps, which Owl 3 ignores".
            // standardActionServiceProps is itself a t.* schema on 20, so it
            // spreads straight into useProps - the same shape core's own
            // client actions use (see action_install_kiosk_pwa.js).
            props = useProps({ ...standardActionServiceProps });

            setup() {
                const { breadcrumbs } = this.env.config;
                state.hasHomeMenu = true;
                state.hasBackgroundAction = breadcrumbs.length > 0;
                env.bus.trigger("BADIRRA-HOME-MENU:TOGGLED");
                onWillUnmount(() => {
                    state.hasHomeMenu = false;
                    state.hasBackgroundAction = false;
                    env.bus.trigger("BADIRRA-HOME-MENU:TOGGLED");
                });
            }
        }

        if (!nativeHomeMenu) {
            registry.category("actions").add(HOME_MENU_ACTION_TAG, BadirraHomeMenuAction);
        }

        const syncBodyClass = () => {
            document.body.classList.toggle("o_badirra_home_menu_open", state.hasHomeMenu);
        };
        env.bus.addEventListener("BADIRRA-HOME-MENU:TOGGLED", syncBodyClass);

        if (nativeHomeMenu) {
            // Our own action never mounts on Enterprise, so nothing would
            // ever write to `state` - and the navbar reads it through
            // useState to decide whether to collapse. Mirroring the native
            // service's state off its own event keeps that binding working.
            env.bus.addEventListener(NATIVE_HOME_MENU_EVENT, () => {
                const native = env.services[NATIVE_HOME_MENU_SERVICE];
                state.hasHomeMenu = Boolean(native && native.hasHomeMenu);
                state.hasBackgroundAction = Boolean(native && native.hasBackgroundAction);
                syncBodyClass();
            });
        }

        async function toggle(show) {
            if (nativeHomeMenu) {
                // Read at call time, not at start(): service start order is
                // not guaranteed, and by the time anything can click the
                // button every service is up.
                const native = env.services[NATIVE_HOME_MENU_SERVICE];
                if (native) {
                    return native.toggle(show);
                }
            }
            show = show === undefined ? !state.hasHomeMenu : Boolean(show);
            if (show === state.hasHomeMenu) {
                return;
            }
            if (show) {
                await env.services.action.doAction(HOME_MENU_ACTION_TAG);
            } else {
                try {
                    await env.services.action.restore();
                } catch (err) {
                    if (!(err instanceof ControllerNotFoundError)) {
                        throw err;
                    }
                }
            }
        }

        // Expose the proxied state object itself (not a getter-wrapping
        // plain object) so that `useService("badirra_home_menu")`
        // in consuming components (navbar.js) actually re-renders when
        // hasHomeMenu/hasBackgroundAction change.
        state.toggle = toggle;
        state.open = () => toggle(true);
        state.close = () => toggle(false);
        return state;
    },
};

registry.category("services").add("badirra_home_menu", homeMenuService);
