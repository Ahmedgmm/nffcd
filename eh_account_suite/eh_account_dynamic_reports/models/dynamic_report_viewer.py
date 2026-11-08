# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Initial options for the interactive dynamic report viewer.

The viewer keeps its own initial options (month to date, every filter
empty) and must start from a handler's defaults only where that handler
really defines a report specific default, such as the quarter a BAS
snapshot covers.
"""

from odoo import models


class EhAccountDynamicReportViewer(models.Model):
    _inherit = 'eh.account.dynamic.report'

    def get_viewer_default_options(self):
        """Return the handler default options that differ from the generic
        handler defaults.

        ``get_default_options`` returns the whole option set of the handler.
        The generic part of it (month to date, the allowed companies, empty
        filters) is what the viewer already starts from, so only the keys a
        handler adds or sets to another value are returned. A report without
        a custom default therefore returns an empty dict and opens exactly
        as before.
        """
        self.ensure_one()
        defaults = self.get_default_options()
        generic = self.env[
            'eh.account.dynamic.report.handler'
        ].build_default_options()
        return {
            key: value
            for key, value in defaults.items()
            if key not in generic or generic[key] != value
        }
