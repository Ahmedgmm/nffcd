# One customer credit limit in Odoo 20

`res.partner.credit_limit` is the authoritative company-dependent customer amount. The existing `eh_credit_limit` API is a writable, non-stored alias to that field. Native warnings and the EH invoice posting gate therefore read the same customer amount. An explicit numeric zero through either field disables the amount check, including during customer creation; the native Partner Limit switch restores the company default. For compatibility, the literal boolean `False` in a legacy EH create payload remains an empty default rather than a numeric override.

`res.company.account_credit_limit` owns the company default using Odoo's native company-dependent fallback. Every EH policy displays this same default. Changing Company Credit Limit on any policy changes that company default, not a private amount belonging to the policy. Policies still own enforcement mode, draft/sales-order exposure choices and the override group. Assign different amounts directly to commercial customers. Disabling Odoo's native warning-banner setting does not disable an EH blocking policy.

Only an EH Accounting Manager can alter credit amounts or restore a customer to the company default. Existing contact access and company scope still apply. Policy managers can edit the single company-default scalar through the policy without receiving general company-configuration write access.

## Upgrade from separate EH amounts

The 20.0.1.4.0 migration retains the original customer JSON and policy amounts as read-only evidence before replacing the EH amount fields.

- An absent native company default adopts the previous active default policy's amount.
- An absent native customer override adopts previous explicit EH customer terms or an assigned policy's amount.
- Different explicitly configured native and EH values remain unchanged and create a Credit Limit Review record. A company-default conflict pauses affected invoice posting for the company; a customer conflict pauses it for that customer.
- Historical subsidiary terms that would change a different commercial customer's credit limit require review.
- A manager chooses Keep Native Limit or Use Previous EH Limit. Both original values, the resolved value, actor and time remain recorded. Keeping native uses the current native value, so a deliberate manager correction made during review is retained.
- Pending customer conflicts must be resolved before the customer can be reparented. Editing a numeric limit alone does not remove the review requirement.

After migration, previously assigned policy amounts are customer terms. Archiving or changing an enforcement policy does not silently erase those customer amounts. Review them explicitly when changing commercial terms.

## Overrides

An override remains specific to one invoice and retains its append-only audit log. The saved review is bound to the customer amount and enforcement inputs as well as invoice inputs. Changing those inputs requires a fresh review. The reason author's current override-group membership is checked again at posting. Override Validity defaults to 24 hours; zero disables time expiry. Expired reasons must be reviewed and saved again.

## Verification

The module test selection passed 80 tests, including the existing browser checks, in a dedicated Odoo 20 Community database. Added tests cover native/EH synchronization, shared company defaults, explicit zero and reset behavior, unauthorized native/context changes, company isolation, changed/revoked/expired overrides, legacy conflict handling and review permissions.

A separate database installed the previous 20.0.1.3.0 release, seeded conflicting and nonconflicting company/customer/policy values, and upgraded to 20.0.1.4.0. Assertions verified that conflicting native values were retained, unambiguous old customer/policy terms migrated, an absent native default adopted its old EH amount, original evidence remained, and pending review blocked posting.
