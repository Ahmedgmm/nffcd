# Purchasing Alternatives — Odoo 20 Community

Open a draft/sent RFQ, then **Alternative Generator**. Add vendor columns,
enter quantities and unit prices in the RFQ currency, and compare untaxed totals.
The lowest positive offered price is highlighted. Set the original column quantity
to its remaining share before using **Create split RFQs**; allocation above the
requested quantity is rejected. Partial allocation is allowed.

**Main PO** applies a column to the existing RFQ. **Extra PO** creates a separate
draft RFQ for that column. **Create split RFQs** creates draft RFQs for alternative
vendors and updates the original quantities. No order is confirmed automatically.
Applying a main vendor or split finalizes the comparison and prevents repeat apply.
Generated extra RFQs are intentional independent documents; clicking Extra PO again
creates another RFQ. Quantities and prices must be finite and non-negative.

Requires only mail, web and purchase_stock. Standard requisition fields are
retained when available. Standard alternative RFQ grouping is used only when
purchase_alternative is installed.

Purchase users can manage comparisons within their allowed companies. Offer cells
must reference a vendor and RFQ line belonging to the same comparison.

Validation: `scripts/verify_purchasing_alternatives.py` runs rollback-only on nffcd-03
using the Community launcher shell. Results: `docs/testing/purchasing_alternatives/`.
