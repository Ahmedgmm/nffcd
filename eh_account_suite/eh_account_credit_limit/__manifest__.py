# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
# All implementation work is original. Credit-limit enforcement is a
# standard pattern from corporate finance practice; the implementation
# is composed against the public Odoo account.move post pipeline. No
# code or comments derive from any proprietary or third-party module.
#
##############################################################################
{
    'name': 'Customer Credit Limit',
    'summary': 'Hard customer credit limit enforcement for Odoo 20 Community that blocks the invoice at post time instead of just showing a number. Per-company credit policy, optional per-partner limit override, warn-or-block enforcement, manager override with reason recorded in an append-only audit log, and a live OK/Warn/Over exposure badge on the partner form. Search terms: odoo customer credit limit, block invoice over credit limit, accounts receivable credit control, hard credit limit enforcement, credit hold, per-partner credit limit, credit policy per company, customer exposure receivable, credit limit manager override audit log.',
    'description': """Odoo's standard credit_limit field is informational only. Nothing stops an over-limit customer invoice from posting. This module uses the native company-scoped customer credit limit as its single amount authority and adds a controlled invoice posting gate.

Define one credit policy per company. Every policy displays the same native company default limit and controls whether enforcement warns or blocks, whether draft customer invoices and the not-yet-invoiced portion of confirmed sales orders count toward exposure (both opt-in, both off by default), and which group may override. A commercial customer can carry its own native limit and an enforcement-policy override; child contacts share that control. Upgrade migration retains previous values and pauses affected posting when native and EH terms conflict until a manager resolves them.

When a customer invoice (out_invoice or out_refund) posts, the gate computes the commercial customer's exposure across the complete actor-authorised accounting-branch scope and compares it against the effective limit using company-currency rounding. Block mode serialises that decision on the commercial-customer row. A breach raises a clear error naming exposure, limit, and excess until a manager records an override reason on that specific invoice. Warn mode logs the breach and proceeds without the blocking lock.

Every override writes one row to an append-only log capturing user, timestamp, exposure, limit, move amount, excess, and reason. The log model refuses write to anything but the comment and refuses unlink, so the record of who waved a customer through, and why, cannot be quietly edited away. The override is per invoice and bound to the reviewed amount and policy. It expires after the configured validity period (24 hours by default; zero disables expiry).""",
    'author': 'ERP Heritage',
    'website': 'https://www.erpheritage.com.au/',
    'license': 'LGPL-3',
    'category': 'Accounting/Accounting',
    'version': '20.0.1.4.0',
    'depends': ['eh_account_base', 'account'],
    'data': [
        'security/ir.access.csv',
        'views/credit_policy_views.xml',
        'views/credit_limit_review_views.xml',
        'views/res_partner_views.xml',
        'views/account_move_views.xml',
        'data/menus.xml',
    ],
    'images': ['static/description/banner.gif'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
