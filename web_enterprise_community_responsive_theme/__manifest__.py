# Copyright Badirra / Mahmoud Salheen (Mahmoudsalheen47@gmail.com)
# All rights reserved.
# License OPL-1 (Odoo Proprietary License v1.0) - see the LICENSE file.

{
    'name': 'Web Enterprise Community Responsive Theme',
    'summary': 'Enterprise-grade responsive backend theme for Odoo Community: '
               'app switcher, dark mode, refined views and a branded login screen.',
    'description': """
Web Enterprise Community Responsive Theme
==========================================

A professionally built backend theme that brings a modern, responsive,
Enterprise-grade interface to Odoo Community.

Key capabilities
-----------------
* Full-screen app switcher ("waffle" grid) with drag-to-reorder, instant
  search and a six-per-row Enterprise-style layout.
* Redesigned top navigation bar that gets out of the way on the home
  screen and turns into a back control inside an app.
* Complete dark mode across every core widget - not just the navbar and
  app switcher - driven by a properly injected dark variable palette, so
  even addons that ship no dark-mode assets of their own render correctly.
* Optional denser list-view density, remembered per browser.
* Refined kanban cards, a mobile-usable pivot table and a polished mobile
  burger menu.
* Flat, rounded Bootstrap component set and a branded login screen that
  follows the light/dark preference.
* Fully responsive, RTL-ready, and translated into 54 languages including
  Arabic.

Built from scratch against Odoo's public ``web`` addon APIs.

Arabic name: ثيم ويب انتربرايز المتجاوب لأودو المجتمعي

Developed by
------------
* Mahmoud Salheen
* Email: Mahmoudsalheen47@gmail.com
* Website: https://badirra.com
""",
    'version': '20.0.1.1.0',
    'category': 'Themes/Backend',
    'author': 'Badirra',
    'maintainer': 'Mahmoud Salheen',
    'website': 'https://badirra.com',
    'support': 'Mahmoudsalheen47@gmail.com',
    'license': 'OPL-1',
    # Published free for now; the field is here so a price can be set later
    # without restructuring the manifest.
    'price': 0.0,
    'currency': 'USD',
    'depends': ['web'],
    'data': [
        'views/webclient_templates.xml',
    ],
    'assets': {
        'web._assets_primary_variables': [
            ('before', 'web/static/src/scss/primary_variables.scss',
             'web_enterprise_community_responsive_theme/static/src/scss/variables.scss'),
        ],
        'web._assets_backend_helpers': [
            ('before', 'web/static/src/scss/bootstrap_overridden.scss',
             'web_enterprise_community_responsive_theme/static/src/scss/bootstrap_overridden.scss'),
        ],
        'web.assets_frontend': [
            'web_enterprise_community_responsive_theme/static/src/scss/cairo_font.scss',
            'web_enterprise_community_responsive_theme/static/src/webclient/login/login.scss',
        ],
        # NOTE: every .scss/.js/.xml file added anywhere under
        # static/src/webclient/ (navbar, home_menu, color_scheme, login,
        # components, list, kanban, pivot, burger_menu, ...) is picked up
        # automatically by the globs below - no per-file entry is needed.
        'web.assets_backend': [
            # NOTE: static/src/scss/variables.scss and bootstrap_overridden.scss
            # are already injected at the correct spots (before Odoo's own
            # primary_variables.scss / bootstrap_overridden.scss) via the
            # 'web._assets_primary_variables' / 'web._assets_backend_helpers'
            # entries above. Do NOT also glob 'static/src/scss/**/*.scss' here
            # or those two files get compiled a second time, out of order,
            # instead of just once in the right spot.
            'web_enterprise_community_responsive_theme/static/src/scss/cairo_font.scss',
            'web_enterprise_community_responsive_theme/static/src/webclient/**/*.scss',
            'web_enterprise_community_responsive_theme/static/src/webclient/**/*.js',
            'web_enterprise_community_responsive_theme/static/src/webclient/**/*.xml',
            ('remove', 'web_enterprise_community_responsive_theme/static/src/**/*.dark.scss'),
        ],
        'web.report_assets_common': [
            'web_enterprise_community_responsive_theme/static/src/scss/cairo_font.scss',
        ],
        'web.report_assets_pdf': [
            'web_enterprise_community_responsive_theme/static/src/scss/cairo_font.scss',
        ],
        # ---------------------------------------------------------------
        # DARK MODE
        # ---------------------------------------------------------------
        # CRITICAL - why this uses ('before', ...) injection and not a
        # plain append:
        #
        # Odoo's own 'web.assets_web_dark' is defined as
        #     ('include', 'web.assets_web') + 'web/static/src/**/*.dark.scss'
        # i.e. the ENTIRE light bundle is compiled first, then dark files
        # are appended. Appending a file that only reassigns SCSS variables
        # at that point does nothing at all: every stylesheet that reads
        # those variables (core's navbar.scss, all of Bootstrap, ...) has
        # already been compiled with the LIGHT values further up. That is
        # why variable-driven dark-mode fixes silently had no effect while
        # hand-written .dark.scss rules did work.
        #
        # The fix (same approach ica_web_responsive uses): declare a
        # 'web.dark_mode_variables' bundle whose entries INSERT the dark
        # variables immediately BEFORE their light counterparts, then
        # include that bundle into the dark asset bundles. Because both
        # variables files declare every value with '!default', and SCSS
        # '!default' is a no-op once a variable already has a value, the
        # dark file (now first) wins and everything downstream compiles
        # against the dark palette.
        'web.dark_mode_variables': [
            ('before',
             'web_enterprise_community_responsive_theme/static/src/scss/variables.scss',
             'web_enterprise_community_responsive_theme/static/src/scss/variables.dark.scss'),
        ],
        'web.assets_web_dark': [
            ('include', 'web.dark_mode_variables'),
            ('before',
             'web_enterprise_community_responsive_theme/static/src/scss/bootstrap_overridden.scss',
             'web_enterprise_community_responsive_theme/static/src/scss/bootstrap_overridden.dark.scss'),
            'web_enterprise_community_responsive_theme/static/src/webclient/**/*.dark.scss',
        ],
        # The pivot view lives in Odoo 18's lazy-loaded bundle, which is
        # compiled separately and therefore needs the dark variables
        # injected into it too - otherwise the pivot renders with light
        # variables while the rest of the page is dark.
        'web.assets_backend_lazy_dark': [
            ('include', 'web.dark_mode_variables'),
        ],
    },
    # First entry is what Odoo Apps uses as the listing's main image - the
    # animated banner leads, so the listing shows the theme in motion.
    'images': [
        'static/description/banner_screenshot.gif',
        'static/description/screenshot_home_light.png',
        'static/description/screenshot_home_dark.png',
        'static/description/screenshot_list_light.png',
        'static/description/screenshot_list_dark.png',
        'static/description/screenshot_dark_toggle.png',
        'static/description/screenshot_login.png',
    ],
    'installable': True,
    # A backend theme is not an "application" in Odoo's sense - it adds no
    # menu of its own, so it must not appear as a top-level app tile.
    'application': False,
    'auto_install': False,
}
