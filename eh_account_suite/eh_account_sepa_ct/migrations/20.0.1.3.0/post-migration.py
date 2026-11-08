# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Repair the shipped confirmation template sender expression.

The template is loaded with noupdate, so the corrected data file never
reaches an existing database. Its sender used a filter the inline template
engine does not know, which made every render of the template fail. Only
the untouched shipped value is replaced; a customised sender is kept.
"""


_BROKEN_EMAIL_FROM = '{{ (object.company_id.email or user.email) | safe }}'
_FIXED_EMAIL_FROM = '{{ object.company_id.email or user.email }}'


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        UPDATE mail_template AS template
           SET email_from = %s
          FROM ir_model_data AS imd
         WHERE imd.model = 'mail.template'
           AND imd.module = 'eh_account_sepa_ct'
           AND imd.name = 'email_template_eh_sepa_ct_confirmation'
           AND imd.res_id = template.id
           AND template.email_from = %s
        """,
        (_FIXED_EMAIL_FROM, _BROKEN_EMAIL_FROM),
    )
