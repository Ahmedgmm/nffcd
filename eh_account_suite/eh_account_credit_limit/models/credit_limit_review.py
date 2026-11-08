# -*- coding: utf-8 -*-
# Copyright (C) 2026 ERP Heritage (https://www.erpheritage.com.au/).

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL


_REVIEW_CREATE = object()


class EhCreditLimitReview(models.Model):
    _name = 'eh.credit.limit.review'
    _description = 'Credit limit upgrade review'
    _order = 'state, company_id, partner_id, id'

    company_id = fields.Many2one('res.company', required=True, index=True)
    partner_id = fields.Many2one('res.partner', ondelete='restrict', index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    source = fields.Char(required=True)
    native_limit = fields.Monetary(required=True)
    previous_eh_limit = fields.Monetary(required=True)
    state = fields.Selection([
        ('pending', 'Needs Review'), ('resolved', 'Resolved'),
    ], default='pending', required=True, readonly=True)
    resolution = fields.Selection([
        ('native', 'Kept Native Limit'), ('eh', 'Used Previous EH Limit'),
    ], readonly=True)
    resolved_limit = fields.Monetary(readonly=True)
    resolved_by_id = fields.Many2one('res.users', readonly=True)
    resolved_at = fields.Datetime(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su or self.env.context.get('_eh_credit_review_create') is not _REVIEW_CREATE:
            raise AccessError(_("Credit-limit review records are created only by the upgrade."))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_("Credit-limit review evidence is changed only by its resolution actions."))

    def unlink(self):
        raise AccessError(_("Credit-limit review evidence cannot be deleted."))

    @api.model
    def _create_upgrade_review(self, company, partner, native, previous, source):
        # Upgrade-only helper: the migration runs as superuser, with no RPC input.
        if not self.env.su:
            raise AccessError(_("Credit-limit migration requires the upgrade environment."))
        existing = self.search([
            ('company_id', '=', company.id), ('partner_id', '=', partner.id or False),
            ('source', '=', source),
        ], limit=1)
        if existing:
            return existing
        return self.with_context(_eh_credit_review_create=_REVIEW_CREATE).create({
            'company_id': company.id, 'partner_id': partner.id or False,
            'source': source, 'native_limit': native,
            'previous_eh_limit': previous,
        })

    def _resolve(self, choice):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('eh_account_base.group_eh_manager'):
            raise AccessError(_("Only an EH Accounting Manager may resolve credit limits."))
        self.env['eh.credit.policy']._eh_assert_company_allowed(self.company_id.id)
        self.env.execute_query(SQL(
            "SELECT id FROM eh_credit_limit_review WHERE id = %s FOR UPDATE", self.id,
        ))
        self.invalidate_recordset()
        if self.state != 'pending':
            raise ValidationError(_("This credit-limit conflict has already been resolved."))
        target = self.partner_id.with_company(self.company_id) if self.partner_id else self.company_id
        if self.partner_id and self.partner_id.commercial_partner_id != self.partner_id:
            raise ValidationError(_("Review the current commercial customer before resolving these terms."))
        field = 'credit_limit' if self.partner_id else 'account_credit_limit'
        value = self.previous_eh_limit if choice == 'eh' else target[field]
        # Both writes use the manager's permissions and company context.
        if choice == 'eh':
            if self.partner_id:
                target.write({field: value})
            else:
                target._eh_set_native_credit_default(value)
        super(EhCreditLimitReview, self).write({
            'state': 'resolved', 'resolution': choice, 'resolved_limit': value,
            'resolved_by_id': self.env.uid, 'resolved_at': fields.Datetime.now(),
        })
        return True

    def action_keep_native(self):
        return self._resolve('native')

    def action_use_previous_eh(self):
        return self._resolve('eh')


class ResCompany(models.Model):
    _inherit = 'res.company'

    def _eh_set_native_credit_default(self, limit):
        self.ensure_one()
        if not self.env.su:
            self.check_access('read')
            self.env['eh.credit.policy']._eh_assert_company_allowed(self.id)
            if not self.env.user.has_group('eh_account_base.group_eh_manager'):
                raise AccessError(_("Only an EH Accounting Manager may change the company credit limit."))
        # EH policy managers historically edit the default without general
        # company-configuration write access. Elevate only this scalar after
        # the actor, exact company and active company scope have been checked.
        return self.sudo().write({'account_credit_limit': limit})

    def write(self, vals):
        if 'account_credit_limit' in vals:
            if float(vals['account_credit_limit'] or 0.0) < 0.0:
                raise ValidationError(_("A company credit limit cannot be negative."))
            if not self.env.su:
                if not self.env.user.has_group('eh_account_base.group_eh_manager'):
                    raise AccessError(_("Only an EH Accounting Manager may change the company credit limit."))
                if any(company.id not in self.env.companies.ids for company in self):
                    raise AccessError(_("Enable the company before changing its credit limit."))
        return super().write(vals)
