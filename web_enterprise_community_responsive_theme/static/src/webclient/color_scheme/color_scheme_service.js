/** @odoo-module **/

// Copyright Badirra / Mahmoud Salheen - All rights reserved.
// Author: Mahmoud Salheen
// License OPL-1 (Odoo Proprietary License v1.0) - see the LICENSE file.

import { registry } from "@web/core/registry";
import { browser } from "@web/core/browser/browser";
import { cookie } from "@web/core/browser/cookie";
import { session } from "@web/session";
import { user } from "@web/core/user";

// IMPORTANT: this must be the exact cookie name Odoo's own web.layout
// template reads server-side (see addons/web/views/webclient_templates.xml,
// `<t t-if="request.cookies.get('color_scheme') == 'dark'">`) to decide
// whether to serve the "web.assets_web_dark" bundle instead of
// "web.assets_web". Using any other cookie name means the toggle below
// changes nothing: the server would keep serving the light bundle forever.
const COOKIE_NAME = "color_scheme";

// The server-side counterpart, on res.users.settings. Prefixed because
// Enterprise ships its own colour-scheme field on that model - see
// models/res_users_settings.py.
const SETTING_NAME = "badirra_color_scheme";

export function getColorScheme() {
    // session first: it carries the scheme the server actually rendered
    // this page with (ir_http.session_info), so the switch cannot disagree
    // with what is on screen. Reading the cookie instead was the cause of
    // a correctly dark page showing an "off" switch on 17 - the cookie is
    // also rewritten by our controller on every load, making it a second
    // and sometimes stale source of truth.
    //
    // The cookie stays as the fallback for the brief window before session
    // data exists, and for any context where session_info is not present.
    return session.badirra_color_scheme || cookie.get(COOKIE_NAME) || "light";
}

export async function switchColorScheme(scheme) {
    // The cookie is what the current page load reads, so set it first and
    // unconditionally: it makes the reload below correct even if the write
    // to the server fails or the user is somehow not able to save settings.
    cookie.set(COOKIE_NAME, scheme, 365 * 24 * 60 * 60);

    // The saved preference is what makes the choice follow the user to
    // another browser or device. Awaited so the reload cannot race the
    // write and land before it commits.
    try {
        await user.setUserSettings(SETTING_NAME, scheme);
    } catch {
        // Deliberately swallowed. The cookie above already gives this
        // browser the right scheme, so a failed save should degrade to
        // "works here, does not follow me" rather than blocking the
        // toggle outright.
    }

    browser.location.reload();
}

const colorSchemeService = {
    dependencies: [],
    start() {
        return {
            get scheme() {
                return getColorScheme();
            },
            switchTo: switchColorScheme,
        };
    },
};

registry.category("services").add("badirra_color_scheme", colorSchemeService);
