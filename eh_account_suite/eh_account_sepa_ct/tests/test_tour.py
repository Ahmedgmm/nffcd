# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Headless-browser proof that the shipped onboarding tour still loads."""

from odoo.tests import HttpCase, tagged

from odoo.addons.eh_account_base.tests.common import run_tour_as_onboarding


@tagged('eh_tour', 'eh_account_sepa_ct', 'post_install', '-at_install')
class TestSepaCtTour(HttpCase):

    def test_setup_tour_runs_in_the_web_client(self):
        self.start_tour('/odoo', 'eh_sepa_ct_setup_tour', login='admin')

    def test_setup_tour_starts_from_its_database_record(self):
        run_tour_as_onboarding(self, 'eh_sepa_ct_setup_tour', '/odoo')
