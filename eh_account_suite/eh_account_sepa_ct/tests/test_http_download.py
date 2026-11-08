# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""PAIN.001 downloads through the web client's readonly routes.

/web/content and readonly RPC reads run on a read-only cursor (always in
tests, and on production deployments with a read replica). Serving the
verified XML there must not run a query PostgreSQL refuses in a read-only
transaction, which Odoo logs as an ERROR 'bad query' and answers with a
retried request.
"""

import base64

from odoo.tests import HttpCase, new_test_user, tagged

from odoo.addons.eh_account_sepa_ct.models.sepa_export import (
    SEPA_EXPORT_CAPABILITY,
    SEPA_EXPORT_CONTEXT,
)


@tagged('eh_account_sepa_ct', 'post_install', '-at_install')
class TestSepaCtHttpDownload(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        journal = cls.env['account.journal'].create({
            'name': 'CT HTTP Bank',
            'code': 'CTHT',
            'type': 'bank',
            'company_id': cls.env.company.id,
        })
        cls.batch = cls.env['eh.batch.payment'].create({
            'journal_id': journal.id,
            'batch_type': 'outbound',
            'payment_date': '2026-04-30',
        })
        cls.xml_bytes = b'<Document><MsgId>MSG-CT-HTTP-001</MsgId></Document>'
        cls.attachment = cls.env['ir.attachment'].create({
            'name': 'ct_http.xml',
            'type': 'binary',
            'raw': cls.xml_bytes,
            'mimetype': 'application/xml',
            'res_model': cls.batch._name,
            'res_id': cls.batch.id,
        })
        cls.export = cls.env['eh.sepa.export'].with_context(**{
            SEPA_EXPORT_CONTEXT: SEPA_EXPORT_CAPABILITY,
        }).create({
            'batch_id': cls.batch.id,
            'message_id': 'MSG-CT-HTTP-001',
            'transaction_count': 1,
            'control_sum': 25.0,
            'file_hash': cls.env['eh.sepa.export'].compute_hash(
                cls.xml_bytes,
            ),
            'attachment_id': cls.attachment.id,
        })
        cls.manager = new_test_user(
            cls.env,
            login='eh_sepa_ct_http_manager',
            groups='base.group_user,eh_account_base.group_eh_manager',
        )
        cls.auditor = new_test_user(
            cls.env,
            login='eh_sepa_ct_http_auditor',
            groups='base.group_user,eh_account_base.group_eh_auditor',
        )
        cls.plain = new_test_user(
            cls.env,
            login='eh_sepa_ct_http_plain',
            groups='base.group_user,eh_account_base.group_eh_user',
        )

    def _download(self, user, url=None):
        self.authenticate(user.login, user.login)
        url = url or '/web/content/%s?download=true' % self.attachment.id
        # A failed query or a read-only retry is logged at WARNING or above.
        with self.assertNoLogs('odoo', level='WARNING'):
            return self.url_open(url)

    def test_web_content_download_logs_no_error(self):
        response = self._download(self.manager)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.xml_bytes)

    def test_download_button_url_serves_the_verified_file(self):
        # The read-only evidence auditor may download, although the XML is
        # attached to a batch the auditor cannot read.
        action = self.export.with_user(self.auditor).action_download()

        response = self._download(self.auditor, action['url'])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.xml_bytes)

    def test_user_without_export_access_gets_nothing(self):
        response = self._download(self.plain)

        self.assertNotEqual(response.status_code, 200)
        self.assertNotIn(self.xml_bytes, response.content)

    def test_readonly_rpc_read_of_the_bytes_logs_no_error(self):
        self.authenticate(self.manager.login, self.manager.login)
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

    def test_voided_export_is_not_served(self):
        self.export.with_user(self.manager).action_void_for_recut()

        response = self._download(self.manager)

        self.assertEqual(response.status_code, 404)
        self.assertNotIn(self.xml_bytes, response.content)
