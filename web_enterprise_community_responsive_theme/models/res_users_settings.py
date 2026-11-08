# Copyright Badirra / Mahmoud Salheen - All rights reserved.
# Author: Mahmoud Salheen
# License OPL-1 (Odoo Proprietary License v1.0) - see the LICENSE file.

from odoo import fields, models


class ResUsersSettings(models.Model):
    _inherit = "res.users.settings"

    # Deliberately prefixed rather than the bare "color_scheme"
    # ica_web_responsive uses. The manifest advertises Enterprise support,
    # and Enterprise ships its own colour-scheme preference on this same
    # model; two modules declaring one field name with different selection
    # values would collide. The COOKIE, by contrast, must keep the exact
    # name "color_scheme", because that is what Odoo's own web.layout reads.
    #
    # No default and not required on purpose: an empty value means "this
    # user has never chosen", which is what lets the resolution order in
    # ir_http.py fall through to the browser cookie instead of forcing
    # light on everyone the moment the module is installed.
    #
    # res.users.settings lives in base (odoo/addons/base/models/
    # res_users_settings.py) in both 18 and 19 - mail only extends it - so
    # inheriting it here adds no dependency beyond what web already pulls.
    badirra_color_scheme = fields.Selection(
        [("light", "Light"), ("dark", "Dark")],
        string="Badirra Colour Scheme",
        help="Interface colour scheme for the Badirra theme. Stored per "
             "user on the server, so the choice follows the user to any "
             "browser or device.",
    )
