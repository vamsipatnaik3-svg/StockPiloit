# Phase 4F.1 — Analytics and Data Reliability Audit

## Audit scope and evidence

This is an implementation audit, not a proposed metric redesign. I reviewed the analytics routes and schemas, service queries, current-upload lifecycle, branch authorization scope, relevant models, existing metric notes, and regression tests. Findings below are marked **Verified** when directly supported by code and tests. Where the product has not established a definition, the item is marked **Unresolved** rather than inferred.

Primary implementation files:

- `backend/app/api/routes/analytics.py`
- `backend/app/core/branch_scope.py`
- `backend/app/services/analytics.py`
- `backend/app/services/theoretical_consumption_queries.py`
- `backend/app/services/theoretical_consumption.py`
- `backend/app/services/actual_consumption_queries.py`
- `backend/app/services/actual_consumption.py`
- `backend/app/services/variance_intelligence.py`
- `backend/app/services/upload_processing.py`
- `backend/app/models/daily_upload.py`, `backend/app/models/retail_data.py`, and `backend/app/models/stock_movements.py`
- `backend/app/schemas/analytics.py`, `backend/app/schemas/theoretical_consumption.py`, `backend/app/schemas/actual_consumption.py`, and `backend/app/schemas/variance_intelligence.py`

Existing metric notes were also compared with the current implementation. In particular, `docs/owner-analytics-metrics.md` does not yet reflect the ledger reconciliation now implemented by `/waste/overview`, and its broad zero-value wording does not apply to the newer coverage-aware waste response or to the separate `/overview` waste KPI.

## 1. Metric inventory and calculation definitions

All date ranges below use inclusive `business_date` bounds unless stated otherwise. `resolve_period` defaults to the most recent 30 calendar dates ending on `date.today()`, creates an equal-duration immediately preceding comparison period, and rejects reversed or greater-than-ten-year ranges.

| Metric/API | Business meaning and exact calculation | Source, filters, and reliability |
| --- | --- | --- |
| Revenue — `/analytics/overview`, `/sales/trends`, branch and product performance | **Verified:** sum of recorded `SalesRecord.net_amount`. The backend does not recompute net amount from quantity, price, discount, or tax. This preserves workbook financial values. Revenue is distinct from sales quantity. | `SalesRecord` joined to its exact `DailyUpload`; company, selected business dates, current upload, and `COMPLETED` status are required. `net_amount` is Decimal. No matching records yields `null` in overview, not an asserted zero. Reliable as uploaded net sales for records present; period completeness is not established by this metric. |
| Revenue change — overview, trends, branches | **Verified:** `(current - previous) / abs(previous) * 100`, rounded to two decimal places. Previous dates are the immediately preceding period with the same number of calendar days. Change is `null` when prior revenue is absent or zero. | Same current-upload sales filter for each period. It compares reported totals, not coverage-adjusted daily rates. If either period has missing branch-day uploads, the returned change can compare incomplete totals without showing that gap. |
| Transaction count — overview and branch performance | **Verified:** count distinct `(branch_id, business_date, transaction_id)` among rows with `granularity == TRANSACTION` and a non-null transaction ID. Rows are grouped before counting, so multiple line items in one transaction count once. `AGGREGATED` rows do not become fabricated transactions. | `SalesRecord` plus current completed upload. Returns `null` if the scope contains no transaction-level groups. If a selected period mixes transaction-level and aggregated source data, the count covers only transaction-granularity rows; the response has no transaction-count completeness status. **Unresolved:** whether the product wants this partial count displayed when granularity is mixed. |
| Sales lines and sales days — overview | **Verified:** count sales records and count distinct `SalesRecord.business_date` values in the selected company/branch scope. | Current completed sales records. `sales_days` is distinct dates across the whole scope, not expected branch-date pairs. It cannot prove every branch uploaded for every open day, and it does not expose gaps within the selected period. |
| Revenue trend — `/sales/trends` | **Verified:** sum `net_amount` on each date with source rows. For ranges of at most 45 days points are daily; over 45 and at most 180 days points are Monday-start weeks; longer ranges are calendar months. Dates or buckets without source rows are omitted. | Current completed sales uploads only. The service does not fabricate missing dates or fill gaps with zero. Reliable for observed data; incomplete periods need a separate coverage signal before comparing line slopes as full-period performance. |
| Branch performance — `/branches/performance` | **Verified:** sum net revenue and count sales lines by branch. Prior revenue uses the same-duration preceding dates; change uses the revenue-change formula. Transaction count is distinct transactions per branch. Highest/lowest branches are the first/last revenue-sorted rows. | Company and branch scope are applied before grouping. Branches without sales rows in the selected period are omitted, not returned as zero. In Owner company scope, inactive branches remain in the allowed company-wide set and can appear in historical/current result rows; `active_branches` separately counts only active branches. Manager/Analyst scopes exclude inactive branches. **Unresolved:** whether Owner historical comparisons should continue to include closed branches. |
| Product performance — `/products/performance` | **Verified:** sums sales quantity, net amount, and sales-line count per product; sorts by net amount; returns top 10 and lowest 10. Product trends sum quantity and revenue per product/date. Category contribution sums net amount per category. | Current completed sales records, tenant product/catalogue, and optional category. Each product trend carries its recorded product unit; the code does not combine quantities across products. The query does not filter by product classification or active state, so legacy historical products remain present. Category revenue is present only for categorized products. Reliable for source-record sales; no margin or contribution percentage is calculated. |
| Current inventory and expiry — `/inventory/overview`, `/inventory/expiry` | **Verified:** for each `(branch, product, batch)`, selects the latest dated `InventorySnapshot` at or before the as-of date and reports that row's `closing_quantity`. Expired means expiry date before as-of; expiring means as-of through 30 days after as-of, inclusive. | Snapshot must belong to a current completed upload. Quantity and unit are returned as recorded. The response includes `snapshot_date`, but it does not expose ingredient/batch/opening/closing coverage status. It may therefore show a latest observed quantity even when the underlying coverage declaration is partial or absent. It is not a low-stock metric; thresholds are not configured. |
| Waste and damage in `/waste/overview` | **Verified:** evaluates waste and damage independently by ingredient, branch, unit, and business date. When movement-category coverage is `COMPLETE`, the ledger is authoritative and counted once; a positive snapshot value that conflicts with the ledger produces `PARTIAL` and `AMBIGUOUS`. With movements but incomplete ledger coverage, observed ledger quantity is exposed as `PARTIAL`. Snapshot-only positive quantities are exposed as `PARTIAL`. Without positive observations or complete coverage, amount is `null`/`UNAVAILABLE`, not confirmed zero. Snapshot-only value uses snapshot unit cost when all positive quantities have it. Positive ledger quantities currently have null value even when a matching snapshot is present, because the ledger event itself has no cost valuation. | Current completed upload snapshots, current upload-origin movements, and non-voided manual `WASTE`/`DAMAGE` movements. Upload-origin movements from superseded or failed uploads are excluded. Branch filters and company filters apply before aggregation. Separate units are grouped; quantities are not converted. This is the most reliable waste endpoint, with explicit `quantity_coverage_status` and `snapshot_ledger_reconciliation`. |
| Waste KPI in `/analytics/overview` | **Verified:** sums snapshot `damaged_quantity` and `wasted_quantity`; groups by unit. Snapshot unit cost times the combined quantity is used for the waste-value KPI when costs are present. | Uses current completed snapshots, but does **not** use stock movements or coverage declarations. Because snapshot fields are non-nullable and older blank cells were stored as zero, rows with no positive snapshot quantity can yield zero even when category coverage is unknown. This KPI can omit ledger-only events and can present unknown as zero. **Not reliable for dashboard waste totals**; use `/waste/overview` where its statuses are shown. |
| Purchase spend — `/purchases/overview` | **Verified:** sum `PurchaseLine.quantity_received * PurchaseLine.unit_purchase_price`. Overall spend and each supplier/product/day spend are `null` when any included line lacks a unit price. Priced and total line counts are returned. Quantities are grouped per product (and retain the product unit); supplier rows report spend and line counts rather than combined quantities. | Current completed upload version, company, branch scope, and `PurchaseLine.business_date` are used. It does not filter this spending report on `receipt_date`, although actual stock receipt timing uses receipt date. **Unresolved:** should dashboard purchase spend be grouped by upload/business date or physical receipt date? No currency conversion or period-applicable cost valuation is performed. |
| Theoretical ingredient consumption — `/ingredient-consumption/theoretical` | **Verified:** for each sales record, multiplies its quantity by the pinned recipe version's ingredient quantities; selected modifier ingredient amounts are multiplied by recorded modifier selection quantity. Decimal arithmetic is used. Totals are grouped by branch, business date, and ingredient. | Sales must link to a current completed upload. Recipe version is pinned to each `SalesRecord`; its base and modifier mappings are read without rewriting history. Ingredient must be same-company, active, classified `INGREDIENT`, and use the canonical unit. Missing recipe, missing modifier mapping, invalid selection, missing source sales, or unit mismatch is surfaced as unresolved/status reasons; a missing modifier-to-ingredient mapping is not treated as no impact. Returns scope status and unresolved sales. A no-record sales scope is `UNAVAILABLE`, not confirmed zero. Reliable only when status is `COMPLETE`. |
| Actual stock depletion and sales-related consumption — `/ingredient-consumption/actual` | **Verified:** requires opening/closing observations and complete daily movement/category coverage. Period depletion is `first-day opening + eligible inflows during the period - final-day closing`; it does not sum daily opening/closing differences. Known non-sales outflows (waste, staff consumption, damage, adjustments, other outflow, and transfer out) are subtracted to derive actual sales-related consumption. Theoretical consumption is compared as `actual - theoretical`; percentage is null when theoretical is zero. | Current completed upload snapshots, declarations, receipts, and upload-origin ledger movements plus non-voided manual movements. Purchase lines are provenance only; each eligible receipt must match exactly one linked purchase movement, which is counted once. Superseded upload versions are excluded. Transfer pairs are validated and netted in company totals; branch results preserve branch impact. Missing daily evidence remains null/status-coded. Reliable only when both actual and theoretical statuses are `COMPLETE`. |
| Variance intelligence — `/variance/intelligence` | **Verified:** uses actual/theoretical results. Consumption variance is actual sales-related consumption minus theoretical recipe consumption. Waste/damage/staff quantities and adjustments remain separate. Waste/damage rate is respective ledger outflow divided by known non-transfer outflow, times 100; no rate is emitted for zero denominator. Baseline is median with MAD, requiring four complete eligible historical periods; up to eight equal-length prior periods are searched within 730 days. | Current and historical calculations reuse the same company/branch scope, current upload lifecycle, and completeness rules. Incomplete evidence is reported as data quality, not an operational anomaly. Historical incomplete periods are excluded; actual selected comparison periods are exposed on findings. No financial impact is claimed. Thresholds are operational heuristics, not validated business policy. Reliable for review prompts when statuses are complete; not proof of cause. |
| Alerts — `/analytics/alerts` | **Verified:** emits expired/expiring batch alerts from current latest snapshots, inventory reconciliation alerts from current completed upload issues, and missing/stale upload alerts for active branches. Stale means latest completed current business date is more than three days before server `date.today()`. | Alerts are scoped by company and allowed branches. No low-stock threshold alerts exist. The stale-age calculation uses server calendar date, not an explicitly applied branch timezone. |

## 2. Upload history and duplicate prevention

**Verified:** structured sales, modifiers, inventory, and purchases retain `source_upload_id`. Successful correction processing inserts replacement records, changes the prior current upload to `is_current = false`, then marks the new version `COMPLETED` and current within one database transaction. A failed correction rolls back its inserts and current-version changes. A completed current upload is returned unchanged on retry. Sales source uniqueness includes the upload ID, allowing retained historical versions without collisions.

Operational sales and purchase analytics join the record to its exact source upload and require `is_current = true` and `processing_status = COMPLETED`. Inventory analytics use the same current completed filter. Theoretical consumption filters sales to current completed source IDs. Actual consumption loads current completed uploads and scopes snapshots, purchase lines, and upload movements through those IDs. Variance uses those actual/theoretical loaders for current and historical periods. The waste ledger endpoint excludes non-current upload-origin movements and voided movements. These paths do not sum superseded upload facts as current data.

## 3. Role, branch, and company scope

**Verified in `resolve_branch_scope` and route tests:**

| Role | Analytics access | Branch scope |
| --- | --- | --- |
| OWNER | Read access to analytics routes. | Company-wide. The scope includes inactive branches; results may retain closed-branch history. |
| MANAGER | Read access to analytics routes. | Assigned active branches only. Explicit requested branch IDs must be a subset of this scope. |
| ANALYST | Read-only analytics access when an active explicit grant exists. | Company grants resolve to active company branches; branch grants resolve to active granted branches only. Revoked/no grant fails closed. |
| STAFF | No analytics route access. | Separate Staff operational APIs are not analytics dashboards. |

Company ID is taken from the authenticated membership, and query predicates are applied before aggregation. Tests exercise cross-company isolation, Owner company analytics, Manager and selected Analyst scope across all analytics endpoints, absent/revoked Analyst grants, and deactivated branches. Branch performance is a comparison only for branches that have sales rows; the API omits zero-sales branches. Variance branch-peer analysis requires at least three complete peer branches. Historical variance periods use the same authorized scope as the current period.

## 4. Data quality behavior

| Data condition | Observed behavior | Dashboard implication |
| --- | --- | --- |
| No matching sales records | Overview revenue and transaction count are `null`; sales lines/days are zero. A latest upload date can distinguish some uploaded-empty cases from never-uploaded scopes, but no explicit sales-coverage declaration exists. | Do not translate `null` revenue to zero without the upload status/coverage context. In-period missing branch-days are not enumerated. |
| Incomplete inventory coverage | Actual consumption reports `INCOMPLETE`, `UNAVAILABLE`, `UNIT_MISMATCH`, or `INVALID_DATA` with reason codes and null dependent totals. Waste overview distinguishes `COMPLETE`, `PARTIAL`, and `UNAVAILABLE`. | Preserve quantity nulls and statuses. Basic inventory overview does not currently surface declarations and is therefore less suitable for a completeness-sensitive stock KPI. |
| Missing recipe or modifier ingredient mapping | Theoretical scope/item is incomplete and unresolved sales are listed. Modifier options with no mapping cannot be assumed to have no ingredient impact. | Show theoretical totals only for complete status; show missing mapping state separately. |
| Missing purchase cost | Purchase spend is null if any selected purchase line lacks price. Waste financial value is null when positive observed quantity is not cost-covered. Variance intelligence does not report financial impact. | Do not fill costs from current product price or another period. |
| Invalid values or unit | Actual/theoretical status includes `INVALID_DATA` or `UNIT_MISMATCH`; dependent totals are withheld. Units are not silently converted. | Keep the status visible and avoid comparing values across units. |
| Corrected upload | Historical source rows remain linked to the superseded version; current analytics require the current completed version. | No double-counting was found in the reviewed query paths; correction and retry tests exercise the lifecycle. |
| Missing business date | Actual consumption requires one current completed upload and coverage for every calendar date in the selected interval. Missing dates remain incomplete, not presumed closed. | A valid closed-day declaration or operating calendar is not currently available. Long intervals can therefore be incomplete even when a branch was legitimately closed. |
| Explicit zero | New coverage declarations can distinguish complete zero/no-stock from unreported/partial. Legacy v1/v2 inventory blanks have no reliable declarations and are not confirmed zero in coverage-aware calculation paths. | Basic overview's legacy snapshot zero handling is an exception and must not be treated as authoritative. |

## 5. Multi-branch and historical verification

The inspected regression suite contains tests for Owner company-level totals and tenant isolation (`test_analytics.py`), Manager and selected Analyst scope across analytics routes and inactive-branch denial (`test_analytics.py`, `test_analyst_analytics_grants.py`), current-version sales and historical baseline selection (`test_theoretical_consumption.py`, `test_actual_consumption.py`, `test_variance_intelligence.py`), and transfer netting in company totals (`test_actual_consumption.py`). Company totals for actual consumption aggregate compatible canonical-unit values and net paired transfer legs; they do not average branch percentages.

Owner's company-wide scope includes inactive branches by design of the current helper. Manager and Analyst scopes exclude inactive branches. Whether Owner totals/comparisons should retain closed-branch history is a product decision, not a code assumption made by this audit.

## 6. Dashboard readiness

### Ready when source status is shown

- **Sales revenue and product/category sales:** use net sales and quantity from current completed sales uploads; preserve currency, product unit, date scope, and transaction-vs-aggregated limitations.
- **Sales trends:** plot only returned dates/buckets; do not add zero points for missing dates.
- **Branch performance:** display actual result branches, label comparisons as reported-period comparisons, and do not imply omitted branches had zero sales.
- **Expiry lists and latest snapshot observations:** display the snapshot date and batch unit; do not label quantities as complete stock coverage without the declarations.
- **Theoretical consumption, actual consumption, and variance:** present only as reliable values when statuses are complete; keep reason codes, source upload references, and baseline dates accessible.
- **Waste/damage:** use `/waste/overview`, display quantity coverage/reconciliation status and unit, and display value only when cost coverage is complete.
- **Purchase spend:** display only when spend is non-null and distinguish priced-line coverage from total lines.
- **Freshness and upload alerts:** use current upload dates and branch-level alerts; indicate that freshness is based on business dates.

### Requires fixes or product decisions before prominent KPI treatment

1. Do not use `overview.waste_quantity` or `overview.waste_value` as authoritative current waste KPIs. They are snapshot-only, omit ledger-only movement evidence, and can report zero without category completeness. Prefer the coverage-aware waste endpoint while retaining its status.
2. Sales response coverage is observed sales dates, not expected branch-days. Define operating-day/closed-day expectations before presenting a period total or trend as complete.
3. Decide how transaction counts should be labeled when aggregated and transaction-granularity uploads coexist in one period; current count is transaction-only and has no completeness status.
4. Decide whether purchase-spend dates mean upload/business date or physical receipt date. Current spend uses business date; actual receipt movements use receipt date.
5. Decide whether Owner company-wide comparisons should include inactive/closed branches. Manager and Analyst active scopes already exclude them.
6. Expose inventory completeness declarations in basic inventory overview if that page needs to make a complete-stock claim. Current rows are observations, not a completeness assertion.
7. Define how a completed workbook with no Daily Sales rows distinguishes a confirmed zero-sales day from absent/unreported sales. The current theoretical service correctly reports no sales records as unavailable, but no sales-coverage declaration exists.
8. Configure low-stock thresholds and costing policy before adding low-stock, gross-profit, or financial variance KPIs.

## 7. Suggested role dashboard KPIs

These are recommendations based on the current API surface, not new business definitions.

| Role | Suggested KPIs / panels | Constraints |
| --- | --- | --- |
| OWNER | Reported net sales and change; product/category performance; active branch comparison; current inventory/expiry; coverage-aware waste/damage; purchase spend with priced-line coverage; actual/theoretical consumption and variance; stale/missing upload and reconciliation alerts. | Company scope; make inactive-branch inclusion explicit. Keep status, units, source freshness, and missing coverage visible. Avoid overview waste KPI until corrected. |
| MANAGER | Same operational and sales panels for assigned active branches, plus branch-level expiry, waste, receipts/purchases, and consumption. | Never aggregate outside assigned active branches. No company-wide or peer data outside scope. |
| STAFF | Operational workflow status: recent stock counts submitted, waste/damage events submitted, purchase receipt confirmations awaiting/currently recorded, and assigned-branch task completion. | Staff are denied analytics routes. Build panels only from Staff operational APIs; do not expose revenue, supplier spend, or company analytics by implication. |
| ANALYST | Read-only sales, product/category, branch, inventory, purchase, waste, actual/theoretical consumption, and variance views within the explicit grant. | Treat grants as selected authorized scope. Keep data-quality and cost-coverage statuses. No write controls. |

## 8. Test validation

Existing coverage was sufficient for the inspected behavior; no new tests were added because the audit did not change implementation. Relevant test files reviewed include:

- `backend/tests/test_analytics.py`
- `backend/tests/test_analyst_analytics_grants.py`
- `backend/tests/test_theoretical_consumption.py`
- `backend/tests/test_actual_consumption.py`
- `backend/tests/test_variance_intelligence.py`
- `backend/tests/test_upload_processing.py`
- `backend/tests/test_v3_upload_processing.py`

Full backend command: `cd backend && .venv/bin/python -m pytest -q` — **232 passed, 900 warnings** in 20.15 seconds. Warnings are existing Starlette/httpx and deprecated FastAPI status-constant warnings. `git diff --check` passed after adding this report.

## Audit conclusion

The current-upload lifecycle, tenant/branch scoping, Decimal-based theoretical/actual calculations, variance completeness gates, and waste ledger reconciliation have substantial test coverage and can support dashboard views when their status/coverage fields are preserved. Sales and product performance are reliable as summaries of records received, but the APIs do not prove period completeness. The `/overview` waste KPI and basic inventory overview should not be presented as complete, coverage-aware stock metrics. Purchase date meaning, mixed-granularity transaction counts, closed-branch Owner comparisons, and sales closed-day semantics require product decisions before those metrics are presented without qualification.
