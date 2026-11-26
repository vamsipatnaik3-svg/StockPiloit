# Phase 4F.3 — Dashboard Metric Contracts

This document describes metrics currently backed by Tavuno APIs. “Ready” means the metric can be shown with its stated coverage and scope; it does not mean the source data proves all business activity was reported. Values must keep their API units, dates, nullability, and status fields. Do not fill missing observations with zeros.

## Shared contract

- Analytics sources are restricted to the caller's company and authorized branch scope. OWNER may query company scope or a branch; MANAGER is limited to assigned active branches; ANALYST is limited to an active explicit grant; STAFF uses operational APIs and is denied analytics endpoints.
- Sales, purchase, and inventory facts are joined to their exact source upload. Current operational results require `DailyUpload.is_current = true` and `processing_status = COMPLETED`; superseded corrected-upload rows remain historical evidence and are excluded.
- Analytics date ranges are inclusive. Sales use the workbook `business_date`. Purchase spend uses physical `PurchaseLine.receipt_date`; workbook `business_date` remains upload/reporting context. There is no stored purchase order date.
- Amounts use the company currency and recorded Decimal amounts. Sales revenue is uploaded `net_amount`, not a recomputation. Product and ingredient quantities retain their original/canonical units; incompatible units must not be added.
- Coverage labels describe the evidence available to that calculation. `null` means unavailable or incomplete where the endpoint contract says so; it is not zero.

## Metric contracts

| Metric | Definition and calculation | Source tables / endpoint | Date semantics | Branch scope | Coverage and dashboard readiness |
| --- | --- | --- | --- | --- | --- |
| Reported sales revenue | Sum of recorded `SalesRecord.net_amount`. Revenue is separate from quantity sold. Change is `(current - previous) / abs(previous) * 100`, to two decimals; no change is returned if prior is missing/zero. | `sales_records`, `daily_uploads`; `/analytics/overview`, `/sales/trends`, `/branches/performance`, `/products/performance` | Inclusive sales `business_date`; comparison uses the immediately prior period of equal length. | Authorized selected branch set; company totals sum scoped records. | Ready as reported sales, not as proof of complete sales. Use `sales_coverage`; missing branch-days are not zero. Trend points omit absent dates/buckets. |
| Sales quantity / product performance | Sum `SalesRecord.quantity` by product; values preserve each product unit. Product revenue is sum of `net_amount`; sales lines are record count. | `sales_records`, `daily_uploads`, `products`, optional `product_categories`; `/products/performance` | Inclusive `business_date`; only current completed source uploads. | Authorized scope; rows are grouped per product and are not combined across units. | Ready with upload coverage and unit visible. No gross margin or cost-based profit is supplied. |
| Category contribution | Sum recorded net sales by the product's configured category. Uncategorised sales do not become a fabricated category. | Sales records, uploads, products, categories; `/products/performance` | Inclusive sales business date. | Authorized scope. | Ready for reported category revenue only; category configuration and sales coverage can be incomplete. |
| Transaction count | Distinct `(branch_id, business_date, transaction_id)` among `TRANSACTION` rows. Never infer from sales quantities or revenue. | `sales_records`, `daily_uploads`; `/analytics/overview`, `/branches/performance` | Inclusive sales business date; previous comparison uses same-length prior period. | Evaluated per authorized aggregate or per branch. | `COMPLETE` when all rows in scope are transaction-level; `PARTIAL` when transaction and aggregated rows coexist (known transaction count is returned); `UNAVAILABLE` for aggregated-only or no rows (count is null). Overview exposes current/previous coverage and suppresses percent change unless both are complete. Branch rows expose current status. Ready only when status is shown. |
| Sales coverage | Counts authorized branch/calendar-date pairs with completed current upload, uploaded-empty confirmed zero, missing upload, or incomplete upload. | `daily_uploads`, `branches`; `/analytics/overview.sales_coverage` | Inclusive calendar dates; no operating-day calendar exists. | Each authorized branch is assessed independently, then counts are aggregated. | `COMPLETE`/`INCOMPLETE`/`UNAVAILABLE` statuses and date lists distinguish available, confirmed empty, missing, and failed evidence. Ready with the explicit caveat that closed days cannot be inferred. |
| Inventory observation / expiry | Latest current completed snapshot at or before `as_of_date`, per branch/product/batch, reports recorded closing quantity. Expired is expiry before as-of; expiring is as-of through 30 days after, inclusive. | `inventory_snapshots`, `daily_uploads`, products; `/inventory/overview`, `/inventory/expiry` | As-of date; snapshot business date must be on/before it. | Authorized scope; quantities remain per unit/batch. | Quantity is an observation, not automatically a complete-stock assertion. Use `coverage_status` and per-ingredient declarations. Low-stock KPI is unavailable: no thresholds are configured. |
| Waste and damage | Reconciles snapshot category quantities and current, non-voided `WASTE`/`DAMAGE` movements. Complete movement-category coverage makes ledger authoritative; overlaps are not added. Snapshot-only or incomplete observations remain partial; missing is unavailable. | `inventory_snapshots`, `stock_movements`, coverage declarations, uploads; `/waste/overview`; overview reuses its quantity result | Inclusive business/movement date per waste implementation. | Branch/product/unit grouping before company aggregation; no cross-unit summing. | Ready only with `quantity_coverage_status`, reconciliation status, and cost coverage. Ledger event cost is not available, so ledger-only value is not fabricated. |
| Purchase spend | Sum `quantity_received * unit_purchase_price` for receipt lines with known price. If any included line is unpriced, spend is null. | `purchase_lines`, `daily_uploads`, products; `/purchases/overview` | **Physical `receipt_date`** for filter and trend buckets. Upload `business_date` only identifies the source workbook. Missing receipt dates are never assigned another date; response exposes `receipt_date_coverage_status` and `missing_receipt_date_lines`, and spend is withheld if any current scoped line lacks a date. | Same authorized scope for company and branch requests. | Ready when receipt-date coverage is `COMPLETE` and all included lines are priced; otherwise preserve null/partial status. Model currently declares receipt date non-null, so missing-date data should not be representable through normal writes; defensive detection remains. |
| Theoretical ingredient consumption | Sales quantity multiplied by the recipe version pinned to each sale, plus mapped modifier ingredient quantities times recorded modifier selection quantity. Decimal calculations; no implicit unit conversion. | `sales_records`, pinned recipe versions/ingredients/modifiers, products, uploads; `/ingredient-consumption/theoretical` | Sales business date and applicable pinned recipe; selected period inclusive. | Per branch/date/ingredient and authorized requested scope. | `COMPLETE`, `INCOMPLETE`, `UNAVAILABLE`, `UNIT_MISMATCH`, or `INVALID_DATA`; unresolved sales and source versions are exposed. Ready only when complete. |
| Actual ingredient consumption | Period depletion is first-day opening stock plus eligible inflows during the period minus final-day closing stock. Actual sales-related use subtracts known non-sales outflows from depletion. | Snapshots, coverage declarations, purchase lines/linked stock movements, manual/upload movements; `/ingredient-consumption/actual` | Inclusive stock dates; opening at start of first day and closing at end of final day. Uses receipt date for receipt inflows. | Branch rows; company totals net paired transfer legs and aggregate compatible canonical units. | Same calculation statuses as above. Ready only with complete stock/movement evidence; missing quantities remain null. |
| Consumption variance / intelligence | Actual sales-related consumption minus theoretical consumption; percentage only when theoretical denominator is nonzero. Historical anomaly baseline uses eligible complete periods (minimum four; up to eight within lookback); selected windows are exposed. | Actual/theoretical services and variance service; `/variance/intelligence` | Current analysis dates distinct from exposed historical comparison windows. | Authorized branch/company scope; baseline uses same scope. | Ready as a review signal only when complete. Incomplete data is not an anomaly; thresholds are operational heuristics, not established causes or financial impact. |
| Alerts / data freshness | Expiry, inventory discrepancy, missing upload, or stale upload alerts. Stale when latest completed current upload is more than three days old. | Snapshots, upload issues, uploads, branches; `/analytics/alerts` | As-of/business date; stale age currently uses server calendar date. | Authorized active branches. | Ready as operational prompts; not a low-stock or demand prediction. Server-date vs branch timezone is a known limitation. |
| Stock count submissions | Immutable submitted physical quantity observations, grouped by ingredient and optional batch. Corrections reference prior submissions; original evidence stays available. | Stock count submission/line tables; Staff operational APIs | `counted_at` is an aware timestamp; submission time is separately retained. | Staff assigned active branch; manager assigned scope; owner company scope per API. | Ready as recorded task evidence, not automatically reconciled inventory. Unit and branch remain explicit. |
| Waste/damage recording | Immutable manual WASTE or DAMAGE movement with quantity, unit, branch, reason, event timestamp and idempotency key. | Stock movement ledger; Staff operational APIs | Event timestamp interpreted into branch business date by current service rules. | Assigned active branch for Staff/Manager; Owner company branches. | Ready as submitted activity; not a complete waste total absent category coverage. |
| Receipt confirmations | Acknowledgment of a current purchase line; does not create another receipt or stock movement. | Purchase lines, receipt identities, confirmation table; Staff operational APIs | Purchase line physical receipt date; confirmation timestamp is separate. | Assigned active branch for Staff/Manager; Owner company branches. | Ready as workflow acknowledgment. It is not an independent spend or stock-in measure. |

## Dashboard recommendations

### Owner

| KPI or panel | Contract | Readiness |
| --- | --- | --- |
| Company reported net sales and trend | Net sales from current completed uploads; show sales coverage and source date. | Ready with coverage. |
| Transaction count | Known distinct source transactions with current/prior granularity statuses. | Ready with `transaction_count_coverage`; partial counts must be labeled partial. |
| Product and category performance | Recorded revenue and per-product quantity in original units. | Ready with coverage; no margin claim. |
| Inventory and expiry | Latest observed quantity plus ingredient coverage and snapshot date. | Ready as observation; avoid complete-stock label if coverage is incomplete. |
| Waste/damage | Coverage-aware reconciled `/waste/overview`; display unit, status and cost coverage. | Ready with status; financial value may be unavailable. |
| Purchase spend | Price-covered receipts grouped by physical receipt date; expose missing receipt date and pricing coverage. | Ready when complete; do not relabel as order-date spend. |
| Theoretical, actual consumption and variance | Use calculation statuses, reason codes, units and baseline windows. | Ready only for complete data. |
| Branch comparison and alerts | Scoped branch aggregates, upload coverage, freshness, expiry and discrepancy alerts. | Ready with coverage; Owner includes inactive-branch history under current scope behavior. |

### Manager

| KPI or panel | Contract | Readiness |
| --- | --- | --- |
| Assigned-branch sales, revenue, products and transaction count | Same source definitions as Owner, limited to assigned active branches. | Ready with sales coverage and granularity status. |
| Inventory, expiry and waste | Observations and reconciled waste only in authorized branches. | Ready with inventory/waste statuses. |
| Purchase receipts and spend | Receipt-date spend and current branch receipt workflow. | Ready when date/pricing coverage is complete. |
| Consumption and operational priorities | Actual/theoretical status, unresolved recipe data, alerts and Staff workflow evidence. | Ready for complete consumption only; priorities are descriptive, not predictive. |

### Staff

| KPI or panel | Contract | Readiness |
| --- | --- | --- |
| Stock counts | Submitted immutable counts and correction links for assigned active branch. | Ready as operational records. |
| Waste/damage | Submitted ledger events, reason and timestamp for assigned branch. | Ready as recorded events, not total without coverage. |
| Receipt confirmations | Current purchase lines acknowledged and confirmation state. | Ready as workflow state; no duplicate stock movement. |
| Operational task status | Counts/events/receipt confirmations available through Staff operational APIs. | Available task-by-task; no consolidated task completion score is defined. |

Staff has no analytics access. Do not display revenue, supplier spend, company performance, or consumption analytics through implied access.

### Analyst

| KPI or panel | Contract | Readiness |
| --- | --- | --- |
| Sales, trends, products, transactions and comparisons | Same definitions as Owner/Manager inside the explicitly granted company or branch scope. | Ready with coverage and transaction granularity status. |
| Inventory, purchases, waste and consumption | Same status-bearing analytics contracts within grant. | Ready only with completeness, receipt-date, price and unit statuses. |
| Variance and historical comparisons | Findings with actual baseline windows, completeness and reason codes. | Read-only and ready as review signals when complete. |

Analyst access is read-only; no write controls or data outside the explicit active grant should be exposed.

## Unavailable or future metrics

- Gross profit, margin, and financial consumption variance: no approved costing method ties ingredient consumption to sales-period cost.
- Low-stock/reorder KPI: no product-level thresholds or replenishment policy.
- Sales conversion, customer count, and reliable transaction comparisons for aggregated-only data: unsupported by aggregated workbooks.
- Closed-day-adjusted sales rates: no branch operating calendar or closed-day declaration.
- Purchase order-date spend: no purchase order date is stored; receipt date is the approved reporting date.
- Consolidated Staff completion score: no business definition exists across different task types.
- Forecasts and AI-generated recommendations: outside current verified metric contracts.

## Phase 4F.3 changes

- Purchase overview filters and trend buckets now use `receipt_date`; upload `business_date` is retained only for source-upload matching. The additive response fields `receipt_date_coverage_status` and `missing_receipt_date_lines` make missing dates explicit. If any current scoped purchase line lacks a receipt date, spend is withheld rather than assigned to an arbitrary period.
- Overview and branch performance now expose transaction source-granularity coverage. Mixed source rows return the known transaction count as `PARTIAL`; aggregated-only or empty scopes return `null` as `UNAVAILABLE`. Overview percent change is withheld unless both periods are complete.
- Sales revenue and quantity formulas are unchanged.
