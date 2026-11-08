# Copyright Badirra / Mahmoud Salheen - All rights reserved.
# Author: Mahmoud Salheen
# License OPL-1 (Odoo Proprietary License v1.0) - see the LICENSE file.

import logging

from odoo import models
from odoo.http import request

_logger = logging.getLogger(__name__)

COOKIE = "color_scheme"


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _post_logout(cls):
        """Drop the colour-scheme cookie when the session ends.

        The cookie is written with a long expiry and nothing ties it to the
        session, so without this it outlives the logout: the next person to
        sign in on the same browser inherits whichever scheme the previous
        user picked. The switch sits in the user menu beside Preferences,
        so it reads as a per-user setting; carrying it into a different
        account is wrong.

        Odoo's own web module clears its 'cids' cookie in this same hook.
        """
        super()._post_logout()
        request.future_response.set_cookie(COOKIE, max_age=0)

    def _badirra_color_scheme(self, user=None):
        """Resolve the effective colour scheme for the current request.

        Order: the user's saved preference, then the browser cookie, then
        light.

        The saved preference wins so the choice follows the user to any
        browser or device. The cookie is the fallback for the cases where
        no preference is stored - a public/unauthenticated request, or a
        user who has never touched the switch.

        ``user`` can be passed explicitly for the point in the login flow
        where authentication has just succeeded but request.env still holds
        the public user, so reading env.user there would resolve the wrong
        person's preference (see controllers/home.py).
        """
        if user is None:
            user = request.env.user if request else None
        if user and not user._is_public():
            saved = user.sudo().res_users_settings_id.badirra_color_scheme
            if saved in ("light", "dark"):
                return saved
        if request and request.httprequest.cookies.get(COOKIE) == "dark":
            return "dark"
        return "light"

    def session_info(self):
        """Publish the resolved colour scheme to the browser.

        The Dark Mode switch has to know which scheme is actually in effect
        so it can show itself as on or off. Deriving that from the cookie is
        unreliable: the cookie is also rewritten by our own controller on
        every webclient load, so the switch could read one value while the
        page had been rendered from another. That produced a correctly dark
        page with an "off" switch on the 17.0 branch; the same two-sources
        problem existed here.

        Publishing the value here removes the second source. The client
        reads precisely the value the server used to decide what to render,
        so the two cannot disagree.
        """
        info = super().session_info()
        # Guarded because session_info() is on the critical path for every
        # single page load: if resolving the scheme raises for any reason,
        # this theme must degrade to light rather than take the whole
        # webclient down with a 500. The switch showing the wrong state is
        # a cosmetic problem; an unreachable database is not.
        try:
            info["badirra_color_scheme"] = self._badirra_color_scheme()
        except Exception:
            _logger.warning(
                "Badirra theme: could not resolve the colour scheme for "
                "session_info; falling back to light.", exc_info=True
            )
            info["badirra_color_scheme"] = "light"
        return info

    def color_scheme(self):
        """Tell web.layout which stylesheet to serve.

        This override is what makes dark mode work at all on Odoo 19, and
        it has no equivalent on the 18.0 branch.

        On Odoo 18, web.layout decided for itself, straight from the
        request::

            <t t-if="request.cookies.get('color_scheme') == 'dark'">

        so a client-side toggle that set that cookie was enough.

        Odoo 19 moved the decision into Python. web.layout now renders the
        dark bundle from a ``color_scheme`` value handed to it by this
        method (addons/web/models/ir_http.py), and the Community
        implementation is a hardcoded ``return "light"`` - an extension
        point Enterprise overrides. Nothing reads the cookie server-side
        any more, so without this the dark stylesheet is never served and
        the switch appears to do nothing.

        Answering from _badirra_color_scheme() rather than the cookie alone
        also means this branch has no first-render lag: a user arriving in
        a brand-new browser gets their saved scheme on the very first
        request, because the template asks Python at render time. On 18 the
        same case costs one extra page load, since there the cookie has to
        be restored by the controller first.
        """
        return self._badirra_color_scheme()
