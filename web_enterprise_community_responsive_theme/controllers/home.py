# Copyright Badirra / Mahmoud Salheen - All rights reserved.
# Author: Mahmoud Salheen
# License OPL-1 (Odoo Proprietary License v1.0) - see the LICENSE file.

from odoo.addons.web.controllers import home as web_home
from odoo.http import request, route

COOKIE = "color_scheme"


class Home(web_home.Home):
    @route()
    def web_login(self, redirect=None, **kw):
        """Restore the saved colour scheme as part of signing in.

        _post_logout clears the cookie, so a user arrives back at the
        webclient without one. On this branch that does not affect the
        stylesheet - ir_http.color_scheme() answers from the saved
        preference at render time, so the page itself is already correct.

        What it does affect is the switch. The Dark Mode item in the user
        menu reads the cookie to decide whether it shows as on
        (color_scheme_service.getColorScheme), so without this the first
        page after logging back in would be correctly dark while the switch
        sat in the off position - and pressing it would then appear to do
        nothing, because it would be "turning on" what was already on.

        A successful login ends in a redirect to the webclient, so a cookie
        set on that redirect is already in the browser when it requests the
        next page.

        (The 18.0 branch carries the same override for a stronger reason:
        there web.layout picks the stylesheet by reading the cookie while
        rendering, so without this the page itself came back light.)

        The preference is read for request.session.uid explicitly rather
        than from request.env.user: authentication has only just happened
        and the environment can still be carrying the public user, which
        would resolve the wrong person's setting.
        """
        response = super().web_login(redirect=redirect, **kw)
        if request.params.get("login_success") and request.session.uid:
            user = request.env["res.users"].sudo().browse(request.session.uid)
            response.set_cookie(
                COOKIE,
                request.env["ir.http"]._badirra_color_scheme(user=user),
            )
        return response

    @route()
    def web_client(self, s_action=None, **kw):
        """Keep the colour-scheme cookie in step with the saved preference.

        web_login above covers the common path, but the cookie can still
        drift from the stored preference: the user may have changed it in
        another browser, or arrived on an existing session whose cookie was
        cleared. Rewriting it on each webclient load restores it from the
        server rather than leaving the browser stuck on light.

        Bare @route() re-uses the parent's routing configuration (paths,
        auth, readonly) rather than restating it, so this stays correct if
        Odoo changes any of that.
        """
        response = super().web_client(s_action, **kw)
        if getattr(response, "status_code", None) == 200:
            response.set_cookie(
                COOKIE,
                request.env["ir.http"]._badirra_color_scheme(),
            )
        return response
