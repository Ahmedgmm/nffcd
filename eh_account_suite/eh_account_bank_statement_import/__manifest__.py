# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
{
    'name': 'Bank Statement Import',
    'summary': 'Import bank statements into Odoo 20 Community from CSV (per-bank column profiles), OFX, QIF, CAMT.053 (ISO 20022), and MT940 (SWIFT) behind one pluggable parser registry, with idempotent re-import, fuzzy cross-source duplicate flagging, and an audited import history log. odoo 20 bank statement import, odoo community bank statement import, import CAMT.053 odoo, import MT940 odoo, import OFX bank statement odoo, import QIF bank statement odoo, CSV bank statement import per-bank profile, odoo bank statement duplicate detection, idempotent bank statement re-import, ISO 20022 statement import, bank feed connector framework.',
    'description': """Bank Statement Import Pro reads bank statement files into Odoo 20 Community account.bank.statement records, ready for reconciliation. It ships five native parsers behind a single pluggable registry: CSV with a per-bank column profile (column mapping, date format, decimal separator, currency), OFX, QIF (Quicken Interchange Format), CAMT.053 (ISO 20022), and MT940 (SWIFT) including the multi-line :86: extension blocks for end-to-end reference and counterparty extraction. New formats are added by registering a parser class, not by forking the importer. The CSV, QIF, CAMT.053 and MT940 parsers use only the Python standard library; OFX import additionally needs the lightweight ofxparse package (pip install ofxparse), imported lazily so the other four formats work without it.

Duplicate handling is two layers. First, exact per-line idempotency: file and live-feed corridors share one journal-scoped bank-reference key, while lines with no bank reference receive a stable content key. A database constraint means re-importing the same transaction through the same or other corridor skips the line instead of doubling it. Second, a fuzzy cross-source scan catches likely matches whose providers use different identifiers, keyed on journal plus amount to the cent plus a 3-day value-date window plus reference and narration substring overlap. The fuzzy match only flags (it records the suspected original on the line and posts a chatter note), it never blocks or deletes either side, so the operator decides.

Every file import writes a row to the import history log (file hash, user, line count, skipped count, outcome) whether the run succeeded, was a duplicate no-op, or failed, so failed and skipped imports stay in the audit trail with the exact exception text. Bad rows are explicit: a parser raises a precise error naming the offending row, tag, or field, and the wizard records it as an audited error rather than silently dropping data.

A pluggable live-connector framework owns provider profiles, bank-journal binding and scheduled fetches. The base package ships provider placeholders; separate optional Plaid, Basiq and GoCardless modules supply HTTP transports. Each profile runs with isolated failure handling. The optional Plaid adapter collects a complete cursor update before new booked statement lines, change-review evidence and saved progress are committed together. Pending Plaid rows are excluded; corrections, removals and legacy pending replacements affecting existing lines enter Bank Feed Changes without altering existing accounting. Acknowledgement requires review notes and performs no reversal, deletion or unreconciliation. Basiq and GoCardless retain their own flat-transaction adapter contracts. Provider credentials, consent, access and live-service validation remain separate requirements.

Multi-company aware: profiles and statements are scoped through the bank journal, which carries the company. Pairs with the reconciliation workspace that sits on top of the imported statements.""",
    'author': 'ERP Heritage',
    'website': 'https://www.erpheritage.com.au/',
    'license': 'LGPL-3',
    'category': 'Accounting/Accounting',
    'version': '20.0.1.3.11',
    'depends': ['eh_account_base', 'account'],
    'data': [
        'security/ir.access.csv',
        'views/import_profile_views.xml',
        'views/account_bank_statement_line_views.xml',
        'wizards/import_wizard_views.xml',
        'views/import_log_views.xml',
        'views/bank_sync_review_views.xml',
        'views/live_connector_profile_views.xml',
        'data/menus.xml',
        'data/cron.xml',
    ],
    'demo': ['demo/bank_import_demo.xml'],
    'images': ['static/description/banner.gif'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
