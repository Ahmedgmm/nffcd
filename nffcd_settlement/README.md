# Settlement Journals and Trial Balance (Odoo 20 Community)

A distinct `settlement` journal type and separate `settlement_trial_balance` report.
Four debit/credit sections: Opening Balance, Current-period Financial Movements,
Current-period Settlements, Ending Balance. Existing standard trial balance stays unchanged.

Ahmed's revised rule supersedes the original legacy settlement override: **only
entries in a Settlement Journal contribute settlement turnover**. H25 remains general;
its three settlement-labelled summaries are financial movements. A reviewed opening
mapping remains supported, without writing to original posted rows. There is no batch
model and no extra settlement columns.

The handler reuses the standard fiscal-year opening, retained earnings, hierarchy,
company-code SQL, currency conversion, report execution/cache and export engines.
Two additional grouped SQL passes identify explicit opening and settlement activity;
there are no per-account report queries. ORM record rules also restrict journal items.
A scoped frontend prototype patch enables account/group/total drilldown and hides
unsupported analytic controls only for the new report. The addon is self-contained;
no existing EH or shared Odoo source files are changed.

## Install and upgrade

The clean repeatable regression database is `nffcd_settlement_regression_20261123`.
Development databases only: `nffcd_settlement_test_20261123` is synthetic;
`nffcd_settlement_hq_20261123` is a dump/restore copy of the pre-posting HQ stage.
No remote installation or mapping application has been performed.

Use the Community launcher and project configuration with an explicit isolated `-d`:

```
/home/ahemd/WorkSpace/env/bin/python scripts/run_odoo_community.py -c odoo.conf -d nffcd_settlement_test_20261123 -i nffcd_settlement --no-http --stop-after-init --max-cron-threads=0
```

Use `-u nffcd_settlement` for an upgrade and refresh the web assets.
`Odoo Settlement Staging` serves only the synthetic database on localhost:8021.
Customer development/deployment remains a separate explicit instruction.

## Historical review procedure

`docs/testing/settlement/legacy_classification_review.xlsx` contains the exact entry,
company, journal, date, proposed opening/financial purpose and evidence. Subsidiary
candidates remain marked `needs review`. No runtime substring classification exists.
The read-only proposal generator is `scripts/prepare_settlement_review.py`.

Preview through Odoo shell with `NFFCD_MAPPING_FILE` pointing to the exact reviewed
JSON and stdin from `scripts/settlement_legacy_mapping.py`. Redirect stdout to retain
the audit. Preview is the default; it commits nothing. `NFFCD_MAPPING_APPLY=1` applies
only to the two explicitly named isolated development databases. It validates exact
IDs, company, journal ID/code, reference and date, skips unreviewed rows, rejects
conflicts and never duplicates existing mappings. Database-specific records are not
addon installation data. The staging reconciliation tests apply twice inside a
transaction and roll everything back. A remote deployment requires a new reviewed
procedure, including a fresh identity/state check and backup.

## Rollback

Back up the target database and filestore before any future deployment. Unused
settlement journals can fall back to general on uninstall. Uninstall is intentionally
blocked when a Settlement Journal contains entries: silently converting a used
journal would lose the reporting purpose. Archive the feature or restore the full
pre-install backup under an approved rollback plan. Never reset/repost or move posted
entries for rollback. Removing the addon also removes its classification model, so
retain and export its audit records before uninstalling.

## Limits and conventions

- Financial activity includes unpaid sales/purchases, bank/cash, inventory and normal
  intercompany activity. Neither noncash status nor an intercompany account implies
  settlement. Settlement liquidity lines remain allowed under normal validations.
- Explicit opening entries inside the selected period move from standard period
  turnover to opening exactly once. Earlier explicit openings enter historical
  opening normally. Ending balances agree with the standard engine for the same scope.
- Date ranges must stay inside one configured fiscal year, inherited from the standard
  handler. The historical source has December 31 configured. H25 annual reconciliation
  uses June 30 only within a rolled-back staging transaction; no customer fiscal
  configuration changed. The staging H25 snapshot contains drafts, so that comparison
  explicitly includes drafts. Live H25 is posted, verified independently read-only.
- Comparison blocks, cash basis and analytic allocations/columns are explicitly
  unavailable. Partner/account/journal/company filters remain supported. No automatic
  intercompany elimination and no reconstruction of annual summaries into months.
- A shared account with multiple root-company codes appears once; its first sorted
  nonempty code is used for the consolidated row. Amounts aggregate by account identity.
- Opening/ending cell drilldown contains both signs forming the net balance. A zero
  side returns no items. Retained-earnings account drilldown also includes rolled
  prior-year P&L sources. Currency conversion uses the existing engine's closing-date
  rate convention; raw journal-item detail remains in its own company currency.
