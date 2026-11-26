# OWNER analytics metric definitions

All OWNER analytics use validated PostgreSQL records linked to a current `DailyUpload` whose `processing_status` is `COMPLETED`. Queries constrain records by the authenticated membership's `company_id`; optional branch filters are validated against that company. Superseded uploads and raw workbook rows are excluded.

| Metric | Calculation | Database source and availability |
| --- | --- | --- |
| Revenue | Sum `net_amount` over the selected business dates. | `SalesRecord.net_amount`, joined to `DailyUpload`; null when there are no matching records. Decimal precision is retained. |
| Revenue change | `(current - previous) / abs(previous) * 100`, using the immediately preceding period with equal duration. | Same validated sales records; change is null when the previous period is absent or zero. |
| Transaction count | Count distinct `(branch_id, business_date, transaction_id)` for rows whose granularity is `TRANSACTION`. | `SalesRecord`; aggregate rows contribute revenue but never synthetic transactions. Null when no transaction-level records exist. |
| Sales line and day coverage | Count matching sales rows and distinct business dates. | `SalesRecord.business_date` and current completed uploads. |
| Sales trend | Sum net sales for each day; group to Monday-based weeks for ranges over 45 days and calendar months for ranges over 180 days. | `SalesRecord.business_date`, `net_amount`; trend periods omit dates with no records. |
| Active branches | Count active branches in the company, or the selected branch when filtered. | `Branch.is_active`; not inferred from sales activity. |
| Branch performance | Sum sales by branch; compare with each branch's same-duration previous period using the revenue-change formula above. | `SalesRecord`, `DailyUpload`, and `Branch`. Branches without sales in the selected period are omitted from the ranking. |
| Product performance | Sum sales quantity and net amount by product; category revenue is summed by category. Per-product trend rows retain the product's recorded unit. | `SalesRecord`, `Product`, and optional `ProductCategory`. Different products/units are not converted or combined. |
| Current inventory | Select the latest dated snapshot at or before the selected as-of date for each branch, product, and batch. | `InventorySnapshot` joined to current completed `DailyUpload`; quantities retain `InventorySnapshot.unit`. |
| Expired / expiring batches | Current on-hand batch quantity where expiry is before the as-of date, or from the as-of date through 30 days after it. | Latest qualifying `InventorySnapshot.expiry_date` and `closing_quantity`. |
| Waste quantity and trend | Sum recorded damaged and wasted quantities separately, grouped by product, branch, unit, and business date as applicable. | `InventorySnapshot.damaged_quantity`, `wasted_quantity`, `unit`. No unit conversion is applied. |
| Waste value | Sum `(damaged_quantity + wasted_quantity) * unit_cost` only when every positive-waste record has a unit cost. | `InventorySnapshot.unit_cost`; value is null when required costs are missing. Zero is returned only when matching inventory data exists and records no positive waste. |
| Purchase spending | Sum `quantity_received * unit_purchase_price`; total spend is null if any matching line lacks a unit price. | `PurchaseLine`, joined to current completed `DailyUpload`. Supplier, product and daily totals preserve missing-price uncertainty. |
| Operational alerts | Expiry alerts use current snapshot batches; reconciliation alerts use recorded `INVENTORY_RECONCILIATION` issues; missing/stale alerts inspect current completed uploads for active branches. | `InventorySnapshot`, `UploadValidationIssue`, `DailyUpload`, and `Branch`. |

Gross profit is unavailable because no reliable costing method is configured. Low-stock alerts are unavailable because there are no product thresholds. Stock turnover is unavailable because compatible inventory movement history is insufficient. No synthetic transaction counts, missing-value zeros, or product unit conversions are introduced.
