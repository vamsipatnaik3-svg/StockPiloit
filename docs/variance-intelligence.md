# Phase 4D: Variance Intelligence

## Purpose and evidence

The service at `GET /api/v1/analytics/variance/intelligence` derives read-only findings from the existing Phase 4C.5 actual-consumption calculator, current-completed upload versions, declared stock coverage, and the stock movement ledger. It creates no stored findings and does not modify source data. Access follows the existing OWNER-only analytics policy. The existing `/analytics/alerts` contract remains unchanged; it continues to provide expiry, reconciliation, and upload freshness alerts.

The result is evidence of an unusual observed pattern, not proof of its cause. Theft, overportioning, employee conduct, and process failure are not inferred. Recommendations are review prompts only.

## Metrics

- Consumption variance = actual sales-related consumption minus theoretical recipe consumption. Positive means actual exceeds theoretical; negative means it is below theoretical. Percentage is only meaningful when theoretical quantity is nonzero.
- Actual status and theoretical status must both be `COMPLETE` before variance intelligence can describe a complete comparison.
- Waste quantity, damage quantity, staff consumption quantity, and positive/negative adjustment quantities remain separate metrics and use the ingredient's canonical unit.
- Waste rate = waste movement quantity divided by known non-transfer stock outflow quantity, multiplied by 100. Transfer legs are excluded. The rate is omitted at a zero denominator or when actual movement coverage is incomplete.
- Financial impact is not reported. No period-applicable cost can be established by this intelligence layer, so it does not multiply quantities by a guessed or unrelated price.
- Company totals and percentages are not created by averaging branch percentages. Phase 4C.5 nets paired transfers for its company consumption total. Branch peer comparisons require at least three complete branches for the same ingredient and period.
- Company-scope findings use Phase 4C.5 company totals, whose numerators and denominators are aggregated before ratios are calculated. Branch comparisons are emitted for waste rate, damage rate, and theoretical variance percentage; peers must use the same canonical ingredient unit and dates.

## Baseline method and defaults

Baselines use up to eight preceding, equal-length, non-overlapping periods, limited to the preceding 730 days. Each window is anchored to the same weekday pattern using a 7-day-multiple stride; non-week-multiple windows can therefore have gaps. At least four complete periods are required. Missing, incomplete, unit-mismatched, invalid, or unavailable periods are excluded; fewer than four yields `INSUFFICIENT_BASELINE`, never a normal result. The result does not claim seasonal adjustment.

For a metric with historical observations, baseline is the median and dispersion is median absolute deviation (MAD). A candidate is anomalous when its absolute distance from the median is at least `max(3.5 × MAD, materiality floor)`. The centralized initial defaults in `backend/app/services/variance_rules.py` are:

- Baseline: 8 periods, minimum 4, maximum historical span 730 days.
- Robust multiplier: 3.5 MAD.
- Quantity/count absolute floor: 1 canonical unit or event; variance also has a 10% of baseline floor.
- Rate floor: 5 percentage points.
- Peer branch floor: 5 percentage points above the same-period median, with 3 complete peers.

These are operational heuristics because no previously established company thresholds were found. They are not statistically proven business rules and should be tuned with operator review. Severity scales by deviation-to-threshold ratio and recurrence, but this first service evaluates a single selected reporting period; therefore persistence evidence is not yet accumulated and findings cannot exceed the severity supported by one observation. Confidence describes data completeness and the number of valid historical periods, not cause certainty. Incomplete evidence is always low confidence.

## States and completeness

- `ANOMALY`: complete current metric and at least four valid periods, crossing its materiality threshold.
- `NORMAL`: complete current metric and sufficient baseline, below threshold. Normal records are returned so clients can distinguish them from missing findings.
- `INSUFFICIENT_BASELINE`: current metric can be measured, but fewer than four complete comparable periods exist. It is not a normal classification.
- `INCOMPLETE_DATA`: stock/theoretical evidence or daily coverage is incomplete. These are data-quality findings, never operational anomalies.
- `UNAVAILABLE`: reserved in the response contract; no operational inference is emitted for unavailable data.

The calculator requires a completed current upload and applicable coverage for each calendar day. Missing days are incomplete, not inferred closed days. v1/v2 history has no invented v3 declarations. `NOT_APPLICABLE` retains its specific declared meaning and is not used to fill missing evidence. The engine relies on Phase 4C.5 for exclusion of superseded upload data, voided manual movements, duplicate purchase receipts, transfer-pair integrity, and unit checks.

## API

`GET /api/v1/analytics/variance/intelligence`

Query filters: `start_date`, `end_date`, `branch_id`, `ingredient_id`, `finding_type`, `severity`, `status`, `offset` (default 0), and `limit` (default 100, max 500). Finding types include `CONSUMPTION_VARIANCE`, `WASTE`, `WASTE_RATE`, `DAMAGE`, `DAMAGE_RATE`, `STAFF_CONSUMPTION`, `POSITIVE_ADJUSTMENT`, `NEGATIVE_ADJUSTMENT`, their adjustment frequency variants, `DATA_QUALITY`, and branch peer findings. Tenant ID is taken from the authenticated membership. Unknown/out-of-company ingredients and branches are rejected under existing analytics conventions.

Each finding provides a stable UUIDv5 identifier from company, branch, ingredient, type, and requested dates; metric and baseline values; absolute/percentage difference; status, severity, evidence, reason codes, recommendation, and limitations. Identical source data and parameters therefore produce stable identifiers and ordering. Pagination is applied after deterministic sorting.

Example shape (values illustrative only):

```json
{
  "start_date": "2026-11-25",
  "end_date": "2026-11-25",
  "branch_id": null,
  "ingredient_id": null,
  "finding_type": null,
  "severity": null,
  "status": null,
  "total": 1,
  "offset": 0,
  "limit": 100,
  "findings": [{
    "id": "<stable UUID>",
    "finding_type": "CONSUMPTION_VARIANCE",
    "status": "INSUFFICIENT_BASELINE",
    "severity": null,
    "confidence": "LOW",
    "metric_value": "2.5",
    "metric_unit": "g",
    "baseline_value": null,
    "data_status": "COMPLETE",
    "reason_codes": [],
    "evidence": {"actual_sales_related_consumption": "12.5", "theoretical_consumption": "10.0"},
    "explanation": "Fewer than four complete comparable historical periods are available; no normal or anomalous classification is made.",
    "recommendation": null
  }],
  "limitations": []
}
```

The metric example is illustrative and not production data.

## Limitations and dashboard guidance

The existing daily coverage model has no explicit closed-day declaration, so missing upload dates stay incomplete. Financial impact is unavailable without a valid applicable cost. The service makes a bounded set of historical period queries per request (up to eight baseline periods plus current period), not an N+1 query per finding; large date windows can therefore require substantial database work. Existing analytics APIs cap a requested period at ten years, while the baseline itself is bounded to 730 days. A future dashboard should render status and completeness alongside the metric and must not turn missing or insufficient results into zero or a normal state.

