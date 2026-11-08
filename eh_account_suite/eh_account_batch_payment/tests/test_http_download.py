# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Sealed batch bank files downloaded through the readonly web routes.

/web/content and readonly RPC reads run on a read-only cursor (always in
tests, and on production deployments with a read replica). Serving the
verified bank file there must not run a query PostgreSQL refuses in a
read-only transaction, which Odoo logs as an ERROR 'bad query' and answers
with a retried request.
"""

import base64

from odoo.tests import HttpCase, new_test_user, tagged

from odoo.addons.eh_account_base.tests.common import (
    EhAccountIntegrationTestCase,
)


@tagged('eh_account_batch_payment', 'post_install', '-at_install')
class TestBatchPaymentHttpDownload(HttpCase, EhAccountIntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        bank_journal = cls.env['account.journal'].create({
            'name': 'Batch HTTP Bank',
            'code': 'BTHT',
            'type': 'bank',
            'company_id': cls.company.id,
        })
        cls.maker = new_test_user(
            cls.env,
            login='eh_batch_http_maker',
            groups='base.group_user,eh_account_base.group_eh_manager',
        )
        cls.checker = new_test_user(
            cls.env,
            login='eh_batch_http_checker',
            groups='base.group_user,eh_account_base.group_eh_manager',
        )
        cls.batch = cls.env['eh.batch.payment'].create({
            'journal_id': bank_journal.id,
            'batch_type': 'outbound',
        })
        cls.env['account.payment'].create({
            'eh_batch_payment_id': cls.batch.id,
            'partner_id': cls.partner_a.id,
            'partner_type': 'supplier',
            'payment_type': 'outbound',
            'journal_id': bank_journal.id,
            'amount': 100.0,
            'date': '2026-04-15',
            'memo': 'INV-HTTP-001',
        })
        cls.batch.with_user(cls.maker).action_confirm()
        cls.batch.with_user(cls.checker).action_post()
        cls.export_bytes = cls.batch.export_file.content
        cls.attachment = cls.env['ir.attachment'].sudo().search([
            ('res_model', '=', cls.batch._name),
            ('res_id', '=', cls.batch.id),
            ('res_field', '=', 'export_file'),
        ])

    def _download(self, url):
        self.authenticate(self.checker.login, self.checker.login)
        # A failed query or a read-only retry is logged at WARNING or above.
        with self.assertNoLogs('odoo', level='WARNING'):
            return self.url_open(url)

    def test_export_action_url_logs_no_error(self):
        self.assertTrue(self.export_bytes)
        action = self.batch.with_user(self.checker).action_export_csv()

        response = self._download(action['url'])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.export_bytes)

    def test_attachment_url_logs_no_error(self):
        self.assertEqual(len(self.attachment), 1)

        response = self._download(
            '/web/content/%s?download=true' % self.attachment.id,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.export_bytes)

    def test_readonly_rpc_read_of_the_bytes_logs_no_error(self):
        self.authenticate(self.checker.login, self.checker.login)
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
            base64.b64decode(result[0]['raw']['content']), self.export_bytes,
        )
