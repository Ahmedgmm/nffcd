# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
eh.sepa.dd.export: audit row per generated PAIN.008 file.

Mirrors the design of eh.sepa.export from the credit transfer module
(file hash, state machine, supersedes prior generation for the same
batch). Kept as a separate model so direct debit and credit transfer
exports can be queried, audited, and reported on independently.
"""

import base64
import binascii
import hashlib
import hmac

from psycopg2.errors import ReadOnlySqlTransaction

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.http.stream import Stream
from odoo.tools import BinaryValue


_SEPA_DD_MIGRATION_CTX = 'eh_sepa_dd_export_migration'


class EhSepaDdExport(models.Model):
    _name = 'eh.sepa.dd.export'
    _description = "SEPA Direct Debit export file"
    _inherit = ['mail.thread', 'mail.activity.mixin', 'eh.workflow.guard']
    _order = 'generated_at desc, id desc'
    _rec_name = 'message_id'

    # The complete generated-file identity is immutable. Users may annotate
    # ``notes`` but cannot replace the batch, attachment, hash, control data,
    # sequence type, actor, timestamp, message ID, or lifecycle state.
    _eh_guarded_fields = (
        'batch_id',
        'message_id',
        'generated_at',
        'generated_by_id',
        'transaction_count',
        'control_sum',
        'file_hash',
        'sequence_type',
        'local_instrument',
        'state',
        'attachment_id',
    )

    batch_id = fields.Many2one(
        'eh.batch.payment', required=True,
        ondelete='restrict', index=True,
    )
    company_id = fields.Many2one(
        related='batch_id.company_id', store=True, readonly=True,
    )
    message_id = fields.Char(
        required=True, copy=False, index=True,
    )
    generated_at = fields.Datetime(
        required=True, default=fields.Datetime.now, index=True,
    )
    generated_by_id = fields.Many2one(
        'res.users', required=True,
        default=lambda self: self.env.user,
    )
    transaction_count = fields.Integer(readonly=True)
    control_sum = fields.Float(digits=(16, 2), readonly=True)
    file_hash = fields.Char(size=64, readonly=True, index=True)
    sequence_type = fields.Selection(
        [
            ('FRST', "First"),
            ('RCUR', "Recurring"),
            ('FNAL', "Final"),
            ('OOFF', "One-off"),
        ],
        readonly=True,
        help=(
            "The sequence type used by every transaction in this file. "
            "Each PAIN.008 export groups one sequence type per file "
            "for clarity; mixed-sequence collections produce multiple "
            "files."
        ),
    )
    local_instrument = fields.Selection(
        [('CORE', "CORE"), ('B2B', "B2B")],
        readonly=True,
        help="SEPA scheme variant used by every transaction in this file.",
    )
    state = fields.Selection(
        [
            ('generated', "Generated"),
            ('downloaded', "Downloaded"),
            ('superseded', "Superseded"),
        ],
        default='generated', required=True, tracking=True,
    )
    attachment_id = fields.Many2one(
        'ir.attachment', readonly=True, ondelete='set null', index=True,
    )
    notes = fields.Text()

    @api.model
    def _eh_require_writable_cursor(self):
        """Refuse row locks on a read-only cursor without a failed query.

        Readonly routes (/web/content, readonly RPC reads) run on a read-only
        cursor where SELECT ... FOR UPDATE fails, and PostgreSQL's refusal is
        logged by Odoo as an ERROR 'bad query'. The attachment read paths
        below move their locked section to a writable cursor first; any
        other caller gets the same ReadOnlySqlTransaction here, before the
        query, which Odoo's HTTP layer answers by retrying the whole request
        on a read/write cursor, where the locks are then taken.
        """
        if self.env.cr.readonly:
            raise ReadOnlySqlTransaction(
                "cannot lock SEPA Direct Debit export rows in a read-only "
                "transaction"
            )

    @api.model
    def _eh_lock_batches(self, batches):
        """Lock export ownership in deterministic company/batch order."""
        self._eh_require_writable_cursor()
        # Callers authorize the export before entering this private locking
        # helper.  A read-only evidence auditor intentionally has no generic
        # ACL on the source batch, so resolve only the already-proven batch
        # ownership under sudo; the SQL below performs no business mutation.
        batches = batches.sudo()
        company_ids = tuple(sorted(set(batches.mapped('company_id').ids)))
        if company_ids:
            self.env.cr.execute(
                "SELECT id FROM res_company WHERE id IN %s "
                "ORDER BY id FOR UPDATE",
                (company_ids,),
            )
        batch_ids = tuple(sorted(set(batches.ids)))
        if batch_ids:
            self.env.cr.execute(
                "SELECT id FROM eh_batch_payment WHERE id IN %s "
                "ORDER BY id FOR UPDATE",
                (batch_ids,),
            )
            batches.invalidate_recordset()
        return batches

    def _eh_lock_for_transition(self):
        """Serialize download/void/supersede against batch generation."""
        self._eh_require_writable_cursor()
        self._eh_lock_batches(self.mapped('batch_id'))
        export_ids = tuple(sorted(self.ids))
        if export_ids:
            self.env.cr.execute(
                "SELECT id FROM eh_sepa_dd_export WHERE id IN %s "
                "ORDER BY id FOR UPDATE",
                (export_ids,),
            )
            self.invalidate_recordset()
        return self

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(_(
                "SEPA Direct Debit exports can only be created by the batch "
                "file generator.",
            ))
        batches = self.env['eh.batch.payment'].browse([
            vals.get('batch_id') for vals in vals_list
            if vals.get('batch_id')
        ])
        self._eh_lock_batches(batches)
        records = super().create(vals_list)
        for rec in records:
            siblings = self.search([
                ('batch_id', '=', rec.batch_id.id),
                ('id', '!=', rec.id),
                ('sequence_type', '=', rec.sequence_type),
                ('local_instrument', '=', rec.local_instrument),
                ('state', 'in', ('generated', 'downloaded')),
            ])
            # Server-initiated supersede of the prior generation; sudo so the
            # state guard passes.
            siblings.sudo().write({'state': 'superseded'})
        return records

    def action_download(self):
        self.ensure_one()
        # Managers and read-only auditors may download; guessed ids must still
        # satisfy export ACLs/company rules before the sanctioned sudo stamp.
        self._eh_check_access('read')
        self._eh_lock_for_transition()
        self._eh_check_access('read')
        self._verify_attachment_integrity()
        # Download is deliberately available to read-only auditors.  The
        # read check above proves access to this exact export; elevate only
        # the engine-owned telemetry state transition, without incorrectly
        # requiring ordinary write ACLs on immutable export evidence.
        self = self.sudo()
        self.state = 'downloaded'
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % self.attachment_id.id,
            'target': 'download',
        }

    def _assert_downloadable(self):
        """Fail closed when an export has been retired from circulation."""
        self.ensure_one()
        if self.state not in ('generated', 'downloaded'):
            raise UserError(_(
                "Export %s has been superseded and is retired. Its XML "
                "file cannot be downloaded or served; use the active "
                "replacement export instead.",
                self.message_id,
            ))

    def _verify_attachment_integrity(self, attachment=None, content=None):
        """Return verified PAIN.008 bytes, or fail closed on mismatch.

        Accepting the exact bytes from a caller binds verification to the
        bytes returned over HTTP/RPC and removes a check/use race against
        mutable external storage.
        """
        self.ensure_one()
        self._assert_downloadable()
        attachment = attachment or self.attachment_id
        if not attachment or attachment.id != self.attachment_id.id:
            raise UserError(_(
                "Export %s has no valid attached XML file. Generate a fresh "
                "export from the batch.",
                self.message_id,
            ))
        # Export ACL/company rules are checked before this helper is reached.
        # The underlying binary is attached to the source batch, so inspect
        # the server-owned attachment linkage under sudo to let a read-only
        # auditor verify evidence without granting generic batch attachment
        # access.
        attachment = attachment.sudo()
        if attachment.res_model != 'eh.batch.payment' \
                or attachment.res_id != self.batch_id.id:
            raise UserError(_(
                "The XML attachment for export %s is not linked to its "
                "source batch. Download was blocked.",
                self.message_id,
            ))
        if content is None:
            raw = attachment.sudo().raw
            content = raw.content if raw else b''
        if isinstance(content, (bytearray, BinaryValue)):
            content = bytes(content)
        if not isinstance(content, bytes):
            raise UserError(_(
                "The stored XML for export %s is not a byte stream.",
                self.message_id,
            ))
        actual_hash = self.compute_hash(content)
        if not self.file_hash or not hmac.compare_digest(
                self.file_hash, actual_hash):
            raise UserError(_(
                "The stored XML for export %s no longer matches its SHA-256 "
                "audit fingerprint. Download was blocked because the file "
                "may have been replaced or corrupted.",
                self.message_id,
            ))
        return content

    def action_void_for_recut(self):
        """Explicitly retire this export so its batch may be re-collected.

        action_export_sepa_dd refuses to generate a second PAIN.008 while a
        live (generated/downloaded) file exists for the batch, because a
        second file re-consumes every mandate (double-advancing the
        FRST -> RCUR counter) and cuts a duplicate collection the bank could
        debit twice. When a file was genuinely NOT submitted to the bank
        (rejected, lost, never transmitted) and the collection must be
        re-cut, a manager voids it here first: this flips the audit row to
        'superseded' and records who did it, so the trail shows the file was
        retired on purpose rather than silently overwritten. Voiding does NOT
        re-collect; the manager then triggers a fresh export deliberately.
        This is the escape hatch action_export_sepa_dd's refuse message
        promises ("Void the existing export first").
        """
        self._eh_check_access('write')
        if not self.env.user.has_group('eh_account_base.group_eh_manager'):
            raise UserError(_(
                "Only an EH Accounting Manager can void a SEPA Direct "
                "Debit export.",
            ))
        self._eh_lock_for_transition()
        self._eh_check_access('write')
        for rec in self:
            if rec.state not in ('generated', 'downloaded'):
                raise UserError(_(
                    "Export %s is already retired and cannot be voided "
                    "again.",
                    rec.message_id,
                ))
        # Sanctioned state transition: run the guarded write as su, but post
        # the audit note as the real manager so the trail names who voided it.
        self._eh_workflow_action().write({'state': 'superseded'})
        for rec in self:
            rec.message_post(body=_(
                "SEPA Direct Debit export voided for re-cut by %(user)s. "
                "This file must NOT be submitted to the bank; a fresh "
                "export supersedes it.",
                user=self.env.user.display_name,
            ))
        return True

    @staticmethod
    def compute_hash(content_bytes):
        return hashlib.sha256(content_bytes).hexdigest()

    def unlink(self):
        if not self.env.su:
            raise AccessError(_(
                "SEPA Direct Debit export audit rows cannot be deleted.",
            ))
        return super().unlink()


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def _eh_dd_export_refs(self):
        if not self.ids:
            return self.env['eh.sepa.dd.export']
        return self.env['eh.sepa.dd.export'].sudo().search([
            ('attachment_id', 'in', self.ids),
        ])

    def _eh_dd_authorized_export_refs(self):
        """Return refs only after checking the real caller's export ACL."""
        exports = self._eh_dd_export_refs()
        if exports:
            exports.sudo(False)._eh_check_access('read')
        return exports

    def _eh_dd_on_writable_cursor(self, method_name, *args, **kwargs):
        """Run ``method_name`` on these attachments on a writable cursor.

        Serving PAIN.008 bytes takes row locks that serialize the download
        against a void or a re-cut (_eh_dd_authorized_locked_export_refs).
        /web/content and readonly RPC reads run on a read-only cursor, where
        those locks cannot be taken. Instead of letting the lock query fail
        (an ERROR 'bad query' plus a retry of the whole request), the locked
        read runs, whole, on a read/write cursor: the same checks, locks and
        verified bytes as on a read/write request. This is the pattern of
        Odoo's own /web/assets route (web/controllers/binary.py): the
        read-only snapshot is dropped first, then a read/write cursor is
        opened; a test cursor refuses a read/write cursor on top of a
        read-only one that still holds a transaction.
        """
        self.env.cr.rollback()
        with self.env.registry.cursor() as rw_cr:
            records = self.with_env(self.env(cr=rw_cr))
            return getattr(records, method_name)(*args, **kwargs)

    def _eh_dd_authorized_locked_export_refs(self):
        """Authorize before raw locks, then recheck after serialization."""
        exports = self._eh_dd_authorized_export_refs()
        if exports:
            exports._eh_lock_for_transition()
            exports.sudo(False)._eh_check_access('read')
        return exports

    def _can_return_content(self, field_name=None, access_token=None):
        exports = self._eh_dd_export_refs()
        if exports:
            exports.sudo(False)._eh_check_access('read')
            return True
        return super()._can_return_content(field_name, access_token)

    def write(self, vals):
        if not self.env.su and self._eh_dd_export_refs():
            raise AccessError(_(
                "A generated SEPA Direct Debit XML attachment is immutable.",
            ))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and self._eh_dd_export_refs():
            raise AccessError(_(
                "A generated SEPA Direct Debit XML attachment cannot be "
                "deleted.",
            ))
        return super().unlink()

    def _read_format(self, fnames, load='_classic_read'):
        if (
            self.env.su
            and self.env.context.get(_SEPA_DD_MIGRATION_CTX)
        ):
            # The versioned migration must read legacy bytes before it can
            # independently verify their stored hash and either recover the
            # local-instrument identity or quarantine the export.  Normal
            # callers cannot forge this bypass because superuser provenance
            # is required in addition to the context marker.
            return super()._read_format(fnames, load=load)
        protected_formats = {'raw', 'db_datas'} & set(fnames)
        if (
            protected_formats
            and self.env.cr.readonly
            and self._eh_dd_export_refs()
        ):
            return self._eh_dd_on_writable_cursor(
                '_read_format', fnames, load=load,
            )
        locked_exports = self.env['eh.sepa.dd.export']
        if protected_formats:
            # Reject retired evidence before the storage layer loads any
            # bytes. The later integrity check remains bound to the exact
            # bytes returned for active exports.
            # Lock every referenced export in one globally sorted pass; doing
            # this attachment-by-attachment would reintroduce an AB/BA
            # deadlock for multi-attachment reads in opposite orders.
            locked_exports = self._eh_dd_authorized_locked_export_refs()
            for attachment in self:
                for export in locked_exports.filtered(
                        lambda row: row.attachment_id == attachment):
                    export._assert_downloadable()
        result = super()._read_format(fnames, load=load)
        if protected_formats:
            values_by_id = {values['id']: values for values in result}
            for attachment in self:
                values = values_by_id.get(attachment.id, {})
                content = attachment._eh_dd_read_content(values)
                for export in locked_exports.filtered(
                        lambda row: row.attachment_id == attachment):
                    export._verify_attachment_integrity(
                        attachment=attachment,
                        content=content,
                    )
        return result

    @api.model
    def _eh_dd_read_content(self, values):
        """Return the bytes a read() result releases, or None.

        Binary reads return ``{'content': base64, 'size': ...}``. The web
        client load returns only size and checksum; with no released bytes
        the integrity check then reads the stored attachment itself.
        """
        for field_name in ('raw', 'db_datas'):
            value = values.get(field_name)
            if not isinstance(value, dict) or 'content' not in value:
                continue
            try:
                return base64.b64decode(value['content'] or b'', validate=True)
            except (binascii.Error, TypeError, ValueError) as exc:
                raise UserError(_(
                    "The stored XML attachment could not be decoded."
                )) from exc
        return None

    def _to_http_stream(self):
        self.ensure_one()
        if self.env.cr.readonly and self._eh_dd_export_refs():
            return self._eh_dd_on_writable_cursor('_to_http_stream')
        exports = self._eh_dd_authorized_locked_export_refs()
        if not exports:
            return super()._to_http_stream()
        for export in exports:
            export._assert_downloadable()
        raw = self.sudo().raw
        content = raw.content if raw else b''
        for export in exports:
            export._verify_attachment_integrity(
                attachment=self,
                content=content,
            )
        return Stream(
            type='data',
            data=content,
            mimetype=self.mimetype,
            download_name=self.name,
            etag=self.checksum,
            last_modified=self.write_date,
            size=len(content),
            public=self.public,
        )


class IrBinary(models.AbstractModel):
    _inherit = 'ir.binary'

    def _record_to_stream(self, record, field_name):
        """Route /web/content attachment downloads through PAIN.008
        verification."""
        if (
            record._name == 'ir.attachment'
            and field_name in ('raw', 'db_datas')
            and record._eh_dd_export_refs()
        ):
            return record._to_http_stream()
        return super()._record_to_stream(record, field_name)
