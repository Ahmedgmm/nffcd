# NFFCD Accounting Enhancement (Odoo 20)

Open **Invoicing/Accounting → Cash Management**.

- Every cash journal receives a protected `عام` classification. Create more from a payment dropdown, the journal's Cash Classifications tab, or Classifications & Balances.
- Select Receive, Send, or Internal Transfer. Cash sides choose their own safe's classifications. **Split Amount / توزيع المبلغ** exposes allocation lines; positive allocations must equal the payment total.
- Invoice/bill Register Payment supports classifications and splits too. Group invoices into one payment before splitting; independent batch payments need their own allocation.
- Confirming a transfer posts linked outgoing/incoming payments and reconciles the company transfer account. Both cash sides can split independently. Cancel or reset either side to affect both. Linked allocations are immutable: cancel/delete the draft pair and recreate to change them.
- Internal transfers support cash/bank journals within the same company and currency. Bank payments retain normal outstanding-account/reconciliation behavior; cash payments directly affect the safe account.
- Fund balances and movement reports derive from posted cash-account journal items, not payment state. Drafts do not count. Opening entries and adjustments select a classification on the cash journal-item line. Legacy unclassified cash items appear under `عام` without rewriting historical entries.
- Manual split journal items have `cash_allocation_ids` in company currency. Payment splits populate these automatically. Reversals preserve allocations and reverse their signed movement.
- **Transfer Between Classifications** creates a draft entry within one safe. It changes classification balances without changing the safe total; normal journal-entry approval still applies.
- Turn off **Allow Negative Balance** to enforce the posted remaining balance. Safes are locked and row versions bumped during posting to serialize concurrent spending under Odoo's repeatable-read isolation. No draft reservation or historical daily-balance enforcement is included.
- Statements show opening balance, period receipts/spending/transfers, running balance and closing balance. Print PDF or use the movement list's standard export. Amounts are in company currency; filter/group by company when currencies differ.
- Optional Authority integration checks both transfer payments before posting and includes allocations in approval fingerprints. This integration is implemented but has not been integration-tested with Authority installed in this local preview.

## Local preview

The local `20nffcd_demo` was found with base modules only and one company on 2026-11-15, unlike historical project notes. Its pre-install backup is `backups/20nffcd_demo_before_cash_funds_20261115.dump`.

`nffcd_accounting_enhancement` and Accounting are now installed there. `scripts/prepare_cash_funds_preview.py` creates an isolated preview company, two safes, sample posted movements and one draft split receipt. It refuses other databases and duplicate seeding. Run with the project Odoo interpreter/config and feed the file to Odoo shell stdin (non-interactive Odoo shell does not execute `--shell-file`).

Login: `demo.cash.funds`; password: `NffcdDemo@2026`. Sample balances: main safe EGP65,000; activities safe EGP10,000. Draft split receipt EGP5,000 is excluded.

Only PyCharm's **Odoo 20 - nffcd** Python run configuration serves HTTP.

## Validation

Run with `/home/ahemd/WorkSpace/env/bin/python /home/ahemd/WorkSpace/odoo20/odoo-bin -c odoo.conf -d 20nffcd_demo -u nffcd_accounting_enhancement --test-enable --test-tags /nffcd_accounting_enhancement --no-http --stop-after-init`.

Accounting tests cover receipt/spending splits, invalid totals and safe mismatches, paired transfers/cancellation/reset/repost, bank-to-cash, balance guards, posted locks, opening entries, reversals, statement rendering, reclassification, company isolation, invoice-payment splits and the payment-type form onchange.

Browser smoke test: `tests_ui/cash_funds/cash_funds.spec.cjs`; screenshots: `tests_ui/cash_funds/artifacts/`. It reads seeded movements and opens an unsaved transfer form; it does not post transactions.
