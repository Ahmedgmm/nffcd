# Copyright (C) 2026 ERP Heritage (https://www.erpheritage.com.au/)
"""Immutable provider change evidence; review never changes accounting."""

import hashlib
import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class EhBankSyncReview(models.Model):
    _name = 'eh.bank.sync.review'
    _description = 'Bank Feed Change Review'
    _rec_name = 'provider_reference'
    _order = 'create_date desc, id desc'

    profile_id = fields.Many2one('eh.bank.live.connector.profile', required=True, ondelete='restrict', readonly=True, index=True)
    company_id = fields.Many2one(related='profile_id.company_id', store=True, index=True)
    journal_id = fields.Many2one(related='profile_id.journal_id', store=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    statement_line_id = fields.Many2one('account.bank.statement.line', ondelete='set null', readonly=True)
    provider_reference = fields.Char(required=True, readonly=True, index=True)
    change_kind = fields.Selection([('modified', 'Changed'), ('removed', 'Removed'), ('replaced', 'Pending replaced by booked')], required=True, readonly=True)
    event_hash = fields.Char(required=True, readonly=True)
    original_date = fields.Date(readonly=True)
    original_amount = fields.Monetary(readonly=True)
    proposed_date = fields.Date(readonly=True)
    proposed_amount = fields.Monetary(readonly=True)
    proposed_description = fields.Char(readonly=True)
    evidence_json = fields.Text(readonly=True)
    state = fields.Selection([('open', 'Needs review'), ('acknowledged', 'Reviewed')], default='open', required=True, readonly=True)
    resolution_note = fields.Text(string='Review notes')
    reviewed_by_id = fields.Many2one('res.users', readonly=True)
    reviewed_at = fields.Datetime(readonly=True)

    _unique_event = models.Constraint('unique(profile_id, event_hash)', 'This provider change is already recorded.')

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_("Bank feed evidence can only be created by synchronization."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and set(vals) - {'resolution_note'}:
            raise AccessError(_("Bank feed evidence is immutable. Record your decision in Review notes."))
        return super().write(vals)

    def action_acknowledge(self):
        self.check_access('write')
        for review in self:
            if review.company_id not in self.env.companies:
                raise AccessError(_("This bank feed change belongs to another company."))
            if not (review.resolution_note or '').strip():
                raise UserError(_("Add review notes explaining the accounting decision before marking this change reviewed."))
            if review.state == 'open':
                review.sudo().write({'state': 'acknowledged', 'reviewed_by_id': self.env.uid, 'reviewed_at': fields.Datetime.now()})
        return True

    @api.model
    def _queue(self, profile, kind, reference, line, transaction=None):
        evidence = {'kind': kind, 'reference': reference, 'original_line_id': line.id}
        if transaction:
            evidence.update({
                'date': transaction.posted_date.isoformat(), 'amount': transaction.amount,
                'currency': transaction.currency, 'description': transaction.description,
                'counterparty_name': transaction.counterparty_name,
                'pending': bool((transaction.extra or {}).get('pending')),
                'pending_transaction_id': (transaction.extra or {}).get('pending_transaction_id') or '',
            })
        serialized = json.dumps(evidence, sort_keys=True, ensure_ascii=False)
        fingerprint = hashlib.sha256(serialized.encode()).hexdigest()
        existing = self.search([('profile_id', '=', profile.id), ('event_hash', '=', fingerprint)], limit=1)
        if existing:
            return existing
        evidence['original'] = {'date': line.date.isoformat(), 'amount': line.amount,
                                'payment_ref': line.payment_ref, 'move_id': line.move_id.id,
                                'move_state': line.move_id.state, 'reconciled': line.is_reconciled}
        return self.sudo().create({
            'profile_id': profile.id, 'statement_line_id': line.id,
            'provider_reference': reference, 'change_kind': kind, 'event_hash': fingerprint,
            'currency_id': (profile.journal_id.currency_id or profile.company_id.currency_id).id,
            'proposed_date': transaction.posted_date if transaction else False,
            'proposed_amount': transaction.amount if transaction else 0,
            'proposed_description': transaction.description if transaction else False,
            'evidence_json': json.dumps(evidence, sort_keys=True, ensure_ascii=False),
            'original_date': line.date, 'original_amount': line.amount,
        })
