# PDC Management — Odoo 20 Community

Depends only on Community `account` (which supplies mail). Journal settings provide
separate received/issued cheque accounts for registration, deposit, bounce and completion.
Enable the accounting stages you need and configure their accounts; use reconcilable
holding accounts. With every stage disabled, the module only tracks cheque status.

Accounting users can register cheques from posted customer invoices/vendor bills or
from Accounting → Journal Entries → PDC Payments. Company, partner, currency and
invoice direction must match. Registration reconciles the payment against linked
invoices; partial amounts remain partial. Fully settled invoices stay In Payment
until completion. Deposit/bounce/completion move the balance between configured
accounts; completion records the done date. Bounce tracks the balance in its configured
account; cancel the cheque if the invoice must be reopened.

Cancellation unreconciles entries and cancels the linked payment. Resetting a cancelled
cheque preserves cancelled entries for audit and creates a new payment on registration.
Completed cheques require an accountant's reversal; direct cancellation is blocked.
Financial details are locked after registration. Records are isolated by allowed company.
The shared cheque sequence works across companies.

Automated regression tests live in `tests/test_pdc.py`. See
`docs/testing/gm_pdc_odoo20.md` at the project root for validation and limitations.

Existing Odoo 19 database records require a separate migration review (particularly
company assignment and replacement of legacy access rules). This port was validated
on isolated Odoo 20 databases, not by migrating an Odoo 19 database.
