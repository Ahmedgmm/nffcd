# Odoo 20 Community Accounting Pro

One-click install for 50 direct accounting modules on Odoo Community.
This global aggregate contains no accounting engine or transaction model.
Country-specific reporting is installed separately.
It pins, installs, and tests one explicit dependency closure.

## Included closure

| Capability | Modules |
|---|---|
| Foundation | `eh_account_base`, `eh_account_setup` |
| Reporting | `eh_account_dynamic_reports`, `eh_account_dynamic_reports_pro`, `eh_account_dashboard`, `eh_account_dynamic_reports_budget` |
| Receivables | `eh_account_reconcile_pro`, `eh_account_bank_statement_import`, `eh_account_batch_payment`, `eh_account_collections`, `eh_account_credit_limit`, `eh_account_recurring_invoices`, `eh_account_pdc`, `eh_account_portal_extra` |
| Payables | `eh_account_ap_automation`, `eh_account_approval` |
| Assets and leases | `eh_account_assets_pro` |
| Period close | `eh_account_close_workflow`, `eh_account_year_end`, `eh_account_fx_revaluation` |
| Group accounting | `eh_account_intercompany`, `eh_account_consolidation`, `eh_account_intercompany_so_po` |
| Budgeting | `eh_account_budget_pro` |
| Compliance and payments | `eh_account_einvoice_peppol`, `eh_account_sepa_ct`, `eh_account_sepa_dd` |
| AI augmentation | `eh_account_ai_agent`, `eh_account_ai_budget`, `eh_account_ai_collections` |
| IFRS 9, IAS 12 and IAS 37 | `eh_account_ecl`, `eh_account_fair_value`, `eh_account_deferred_tax`, `eh_account_provisions` |
| Revenue and recurring bridge | `eh_account_revenue`, `eh_account_revenue_recurring` |
| Specialist standards | `eh_account_borrowing_costs`, `eh_account_grants`, `eh_account_inventory_nrv`, `eh_account_investment_property`, `eh_account_held_for_sale`, `eh_account_business_combination`, `eh_account_events`, `eh_account_eps`, `eh_account_share_based_payment`, `eh_account_employee_benefits`, `eh_account_costing` |
| Presentation, disclosure and assurance | `eh_account_statements`, `eh_account_disclosures`, `eh_account_audit_pack` |

Australian BAS is optional. Install `eh_account_l10n_au_bas` separately for
Australian reporting; it depends on this suite and Odoo's `l10n_au`.
Installing the global suite alone does not install either Australian module
or create a BAS setup task. The Australian extension owns its onboarding and
keeps Australian or unknown-country tasks pending, while pre-skipping tasks
for companies explicitly outside Australia.

Upgrading an existing suite keeps the Australian module installed. The
migration transfers the existing BAS setup task's external ID to the
Australian extension before obsolete suite data is cleaned up. Task and
progress record IDs, notes, completion actors and dates remain intact; BAS
runs, labels and lodged evidence are not removed.

Bank Statement Import ships five parsers: CSV, OFX, QIF, CAMT.053 and MT940.
SEPA Credit Transfer supports PAIN.001.001.03 and .09.

## Install effects

Order mirroring, AP matching, and asset flows transitively install Odoo Sales,
Purchase and Inventory. Transitive EH EDI Core encrypted credential-vault
runtime requires Python package `cryptography`; aggregate manifest declares
this dependency explicitly. EH EDI Core also creates one idempotent ERP
Heritage support contact; an archived contact stays archived and is never
duplicated.

## One Accounting app

Community names the finance app Invoicing; the suite renames it Accounting
and every suite section lives inside it. When the Odoo Enterprise
`accountant` module is also installed, it already provides an app named
Accounting holding the core finance sections. The suite then files its own
sections in that app and leaves Invoicing its name, so users never see two
Accounting apps. This holds whichever of the two is installed first, and is
reapplied after any module install or update. Uninstalling `accountant`
brings every section back to the Community app under the Accounting name;
uninstalling the suite returns its sections to the menus their own modules
declare and restores the Invoicing name.

## Tested-together contract

`tests/test_suite_contract.py` executes after install and verifies:

- all 50 direct dependencies are installed;
- transitive Sales, Purchase and Inventory applications are installed;
- bundle version is not below any member version;
- manifest, listing, README and parser/schema claims agree;
- the global dependency closure excludes Australian localization and BAS;
- the suite owns no country-specific onboarding records.

The Odoo 20 checks cover the global suite installed alone, the separate
Australian extension installed with its required suite, and an upgrade of an
existing Australian-enabled database. Individual-module success is not used
as a substitute for the aggregate closure. Country-aware lifecycle and
progress-preservation tests live in the optional Australian module.

## Licensing

LGPL-3 across every constituent module in this release.
