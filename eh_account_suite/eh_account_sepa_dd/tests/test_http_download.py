# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""PAIN.008 downloads through the web client's readonly /web/content route.

The download re-verifies the file under row locks that serialize it against
a manager voiding the export. /web/content runs on a read-only cursor
(always in tests, and on production deployments with a read replica), where
those locks cannot be taken. The download must keep its locks, on a
writable cursor, without Odoo logging a failed query or a read-only retry.
"""

import base64

from odoo.tests import HttpCase, new_test_user, tagged


@tagged('eh_account_sepa_dd', 'post_install', '-at_install')
class TestSepaDdHttpDownload(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        journal = cls.env['account.journal'].create({
            'name': 'DD HTTP Bank',
            'code': 'DDHT',
            'type': 'bank',
            'company_id': cls.env.company.id,
        })
        cls.batch = cls.env['eh.batch.payment'].create({
            'journal_id': journal.id,
            'batch_type': 'inbound',
            'payment_date': '2026-04-30',
        })
        cls.xml_bytes = (
            b'<Document><MsgId>MSG-DD-HTTP-001</MsgId></Document>'
        )
        cls.attachment = cls.env['ir.attachment'].create({
            'name': 'dd_http.xml',
            'type': 'binary',
            'raw': cls.xml_bytes,
            'mimetype': 'application/xml',
            'res_model': cls.batch._name,
            'res_id': cls.batch.id,
        })
        cls.export = cls.env['eh.sepa.dd.export'].create({
            'batch_id': cls.batch.id,
            'message_id': 'MSG-DD-HTTP-001',
            'transaction_count': 1,
            'control_sum': 42.0,
            'sequence_type': 'FRST',
            'local_instrument': 'CORE',
            'file_hash': cls.env['eh.sepa.dd.export'].compute_hash(
                cls.xml_bytes,
            ),
            'attachment_id': cls.attachment.id,
        })
        cls.manager = new_test_user(
            cls.env,
            login='eh_sepa_dd_http_manager',
            groups='base.group_user,eh_account_base.group_eh_manager',
        )
        cls.auditor = new_test_user(
            cls.env,
            login='eh_sepa_dd_http_auditor',
            groups='base.group_user,eh_account_base.group_eh_auditor',
        )
        cls.plain = new_test_user(
            cls.env,
            login='eh_sepa_dd_http_plain',
            groups='base.group_user,eh_account_base.group_eh_user',
        )

    def setUp(self):
        super().setUp()
        # Record the cursor every serialization lock is taken on, so the
        # tests prove the locks still run and never on a read-only cursor.
        self.lock_cursors = []
        Export = type(self.env['eh.sepa.dd.export'])
        lock = Export._eh_lock_for_transition
        lock_cursors = self.lock_cursors

        def _eh_lock_for_transition(export):
            lock_cursors.append(export.env.cr.readonly)
            return lock(export)

        self.patch(Export, '_eh_lock_for_transition', _eh_lock_for_transition)

    def _download(self, user, url=None):
        self.authenticate(user.login, user.login)
        url = url or '/web/content/%s?download=true' % self.attachment.id
        # Any failed query or read-only retry is logged at WARNING or above.
        with self.assertNoLogs('odoo', level='WARNING'):
            return self.url_open(url)

    def test_web_content_download_locks_on_a_writable_cursor(self):
        response = self._download(self.manager)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.xml_bytes)
        self.assertEqual(self.lock_cursors, [False])

    def test_download_button_url_serves_the_verified_file(self):
        action = self.export.with_user(self.auditor).action_download()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.lock_cursors.clear()

        response = self._download(self.auditor, action['url'])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.xml_bytes)
        self.assertEqual(self.lock_cursors, [False])

    def test_readonly_rpc_read_of_the_bytes_locks_on_a_writable_cursor(self):
        self.authenticate(self.manager.login, self.manager.login)
        # read() is a readonly RPC, served on a read-only cursor as well.
        with self.assertNoLogs('odoo', level='WARNING'):
            result = self.make_jsonrpc_request(
                '/web/dataset/call_kw/ir.attachment/read',
                {
                    'model': 'ir.attachment',
                    'method': 'read',
                    'args': [[self.attachment.id], ['raw']],
                    'kwargs': {},
                },
            )

        self.assertEqual(
            base64.b64decode(result[0]['raw']['content']), self.xml_bytes,
        )
        self.assertEqual(self.lock_cursors, [False])

    def test_voided_export_is_not_served(self):
        self.export.with_user(self.manager).action_void_for_recut()
        self.lock_cursors.clear()

        response = self._download(self.manager)

        self.assertEqual(response.status_code, 404)
        self.assertNotIn(self.xml_bytes, response.content)
        self.assertEqual(self.lock_cursors, [False])

    def test_tampered_file_is_not_served(self):
        self.attachment.sudo().write({
            'raw': b'<Document><MsgId>SUBSTITUTED</MsgId></Document>',
        })

        response = self._download(self.manager)

        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b'SUBSTITUTED', response.content)

    def test_user_without_export_access_gets_nothing(self):
        response = self._download(self.plain)

        self.assertNotEqual(response.status_code, 200)
        self.assertNotIn(self.xml_bytes, response.content)
        self.assertEqual(self.lock_cursors, [])
