from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from uuid import UUID, uuid5, NAMESPACE_URL

from app.core.branch_scope import BranchAccessScope
from app.services.actual_consumption import calculate_actual_consumption
from app.services.actual_consumption_queries import load_actual_consumption_inputs
from app.services.theoretical_consumption import calculate_theoretical_consumption
from app.services.variance_rules import (
    BASELINE_PERIODS, MAD_MULTIPLIER, MAX_BASELINE_DAYS,
    MIN_ABSOLUTE_VARIANCE, MIN_BASELINE_PERIODS,
    MIN_OPERATIONAL_RATE_POINT_CHANGE, MIN_RELATIVE_VARIANCE_PERCENT,
    SEVERITY_THRESHOLDS,
)

ZERO = Decimal("0")
OUTFLOW_TYPES = {"WASTE", "DAMAGE", "STAFF_CONSUMPTION", "NEGATIVE_ADJUSTMENT", "OTHER_OUTFLOW", "TRANSFER_OUT"}


def _period_data(db, company_id, start, end, branch_id, ingredient_id,
                 branch_scope: BranchAccessScope):
    data = load_actual_consumption_inputs(db, company_id, start, end,
        branch_scope, ingredient_id)
    theoretical = calculate_theoretical_consumption(
        data["theoretical_scopes"], data["theoretical_sales"], company_id)
    data["theoretical_items"] = theoretical["items"]
    data["theoretical_scopes"] = theoretical["scopes"]
    calculated = calculate_actual_consumption(data, company_id, start, end, branch_id, ingredient_id)
    metric_map = {}
    for item in calculated["items"]:
        movement_rows = [m for m in data.get("movements", ())
            if m.branch_id == item["branch_id"] and m.ingredient_product_id == item["ingredient_id"]
            and start <= m.movement_date <= end and m.voided_at is None]
        totals = {kind: sum((m.quantity for m in movement_rows if m.movement_type == kind), ZERO)
            for kind in ("WASTE", "DAMAGE", "STAFF_CONSUMPTION", "POSITIVE_ADJUSTMENT",
                "NEGATIVE_ADJUSTMENT", "OTHER_OUTFLOW", "TRANSFER_OUT")}
        # Internal transfers are excluded from operational outflow rates.
        denominator = sum((m.quantity for m in movement_rows
            if m.movement_type in OUTFLOW_TYPES and m.movement_type != "TRANSFER_OUT"), ZERO)
        metric_map[(item["branch_id"], item["ingredient_id"])] = {
            "item": item, "movements": totals, "outflow_denominator": denominator,
            "adjustment_count": sum(1 for m in movement_rows if m.movement_type in {
                "POSITIVE_ADJUSTMENT", "NEGATIVE_ADJUSTMENT"}),
            "positive_adjustment_count": sum(1 for m in movement_rows if m.movement_type == "POSITIVE_ADJUSTMENT"),
            "negative_adjustment_count": sum(1 for m in movement_rows if m.movement_type == "NEGATIVE_ADJUSTMENT"),
            "reason_codes": sorted({m.reason_code for m in movement_rows if m.movement_type in {
                "POSITIVE_ADJUSTMENT", "NEGATIVE_ADJUSTMENT"} and m.reason_code}),
        }
    if branch_id is None:
        for item in calculated.get("company_totals", ()):
            movement_rows = [m for m in data.get("movements", ())
                if m.ingredient_product_id == item["ingredient_id"]
                and m.branch_id in branch_scope.branch_ids
                and start <= m.movement_date <= end and m.voided_at is None]
            totals = {kind: sum((m.quantity for m in movement_rows if m.movement_type == kind), ZERO)
                for kind in ("WASTE", "DAMAGE", "STAFF_CONSUMPTION", "POSITIVE_ADJUSTMENT",
                    "NEGATIVE_ADJUSTMENT", "OTHER_OUTFLOW", "TRANSFER_OUT")}
            denominator = sum((m.quantity for m in movement_rows
                if m.movement_type in OUTFLOW_TYPES and m.movement_type != "TRANSFER_OUT"), ZERO)
            metric_map[(None, item["ingredient_id"])] = {
                "item": item, "movements": totals, "outflow_denominator": denominator,
                "adjustment_count": sum(1 for m in movement_rows if m.movement_type in {
                    "POSITIVE_ADJUSTMENT", "NEGATIVE_ADJUSTMENT"}),
                "positive_adjustment_count": sum(1 for m in movement_rows if m.movement_type == "POSITIVE_ADJUSTMENT"),
                "negative_adjustment_count": sum(1 for m in movement_rows if m.movement_type == "NEGATIVE_ADJUSTMENT"),
                "reason_codes": sorted({m.reason_code for m in movement_rows if m.movement_type in {
                    "POSITIVE_ADJUSTMENT", "NEGATIVE_ADJUSTMENT"} and m.reason_code}),
            }
    return data, calculated, metric_map


def _metric_value(row: dict, metric: str) -> Decimal | None:
    item = row["item"]
    movement = row["movements"]
    if metric == "CONSUMPTION_VARIANCE":
        return item["absolute_variance"]
    if metric in movement:
        return movement[metric]
    if metric == "WASTE_RATE":
        denominator = row["outflow_denominator"]
        return movement["WASTE"] / denominator * Decimal(100) if denominator > 0 else None
    if metric == "DAMAGE_RATE":
        denominator = row["outflow_denominator"]
        return movement["DAMAGE"] / denominator * Decimal(100) if denominator > 0 else None
    if metric == "ADJUSTMENT_COUNT":
        return Decimal(row["adjustment_count"])
    if metric == "POSITIVE_ADJUSTMENT_COUNT":
        return Decimal(row["positive_adjustment_count"])
    if metric == "NEGATIVE_ADJUSTMENT_COUNT":
        return Decimal(row["negative_adjustment_count"])
    return None


def _threshold(metric: str, baseline: Decimal, mad: Decimal) -> Decimal:
    robust = MAD_MULTIPLIER * mad
    if metric == "CONSUMPTION_VARIANCE":
        return max(robust, MIN_ABSOLUTE_VARIANCE,
            abs(baseline) * MIN_RELATIVE_VARIANCE_PERCENT / Decimal(100))
    if metric.endswith("_RATE"):
        return max(robust, MIN_OPERATIONAL_RATE_POINT_CHANGE)
    return max(robust, MIN_ABSOLUTE_VARIANCE,
        abs(baseline) * MIN_RELATIVE_VARIANCE_PERCENT / Decimal(100))


def _severity(delta: Decimal, threshold: Decimal, repeats: int) -> str:
    ratio = delta / threshold if threshold else ZERO
    for magnitude, persistence, severity in SEVERITY_THRESHOLDS:
        if ratio >= magnitude and repeats >= persistence:
            return severity
    return "LOW"


def _confidence(count: int, complete: bool) -> str:
    if not complete or count < MIN_BASELINE_PERIODS:
        return "LOW"
    if count >= BASELINE_PERIODS:
        return "HIGH"
    return "MEDIUM"


def _recommendation(kind: str) -> str:
    return {
        "CONSUMPTION_VARIANCE": "Review portion sizes, recipe adherence, stock counts, adjustments, waste, and staff-consumption records. Treat explanations as hypotheses.",
        "WASTE": "Review preparation quantities, expiry and storage practices, and demand for products using this ingredient.",
        "DAMAGE": "Review handling and storage practices for this ingredient.",
        "STAFF_CONSUMPTION": "Review staff-consumption recording and the relevant internal policy.",
        "POSITIVE_ADJUSTMENT": "Review stock-count procedures and the recorded adjustment reasons.",
        "NEGATIVE_ADJUSTMENT": "Verify purchase receipts, stock counts, and recurring adjustment reasons.",
        "POSITIVE_ADJUSTMENT_FREQUENCY": "Review stock-count procedures and recurring positive-adjustment reasons.",
        "NEGATIVE_ADJUSTMENT_FREQUENCY": "Verify purchase receipts, stock counts, and recurring negative-adjustment reasons.",
    }.get(kind, "Review the source records and movement reasons for this ingredient.")


def variance_intelligence(db, company_id: UUID, start_date: date, end_date: date,
        branch_id: UUID | None = None, ingredient_id: UUID | None = None,
        finding_type: str | None = None, severity: str | None = None,
        status: str | None = None, offset: int = 0, limit: int = 100,
        branch_scope: BranchAccessScope | None = None) -> dict:
    if branch_scope is None or branch_scope.company_id != company_id:
        raise ValueError("Variance analysis requires a matching branch access scope.")
    current_data, _, current = _period_data(db, company_id, start_date, end_date,
        branch_id, ingredient_id, branch_scope)
    period_days = (end_date - start_date).days + 1
    # Anchor each equal-length historical window to the same weekday pattern.
    # For non-week-multiple periods, this leaves a non-overlapping gap between windows.
    period_stride = ((period_days + 6) // 7) * 7
    history_count = min(BASELINE_PERIODS, MAX_BASELINE_DAYS // period_stride)
    history: list[tuple[date, date, dict]] = []
    if history_count >= MIN_BASELINE_PERIODS:
        for index in range(history_count):
            end = start_date - timedelta(days=index * period_stride + 1)
            begin = end - timedelta(days=period_days - 1)
            _, _, values = _period_data(db, company_id, begin, end,
                branch_id, ingredient_id, branch_scope)
            history.append((begin, end, values))
    findings: list[dict] = []
    metric_types = (
        ("CONSUMPTION_VARIANCE", "g"), ("WASTE", "quantity"), ("WASTE_RATE", "%"),
        ("DAMAGE", "quantity"), ("DAMAGE_RATE", "%"), ("STAFF_CONSUMPTION", "quantity"),
        ("POSITIVE_ADJUSTMENT", "quantity"), ("NEGATIVE_ADJUSTMENT", "quantity"),
        ("POSITIVE_ADJUSTMENT_COUNT", "events"), ("NEGATIVE_ADJUSTMENT_COUNT", "events"),
    )
    current_data_quality = []
    for key, row in current.items():
        item = row["item"]
        overall = item["comparison_status"]
        if overall != "COMPLETE":
            current_data_quality.append((key, row))
        for metric, unit in metric_types:
            value = _metric_value(row, metric)
            if value is None:
                continue
            complete = item["status"] == "COMPLETE" and (
                item["theoretical_status"] == "COMPLETE" if metric == "CONSUMPTION_VARIANCE" else True)
            if metric in {"WASTE_RATE", "DAMAGE_RATE"} and row["outflow_denominator"] == 0:
                continue
            prior = []
            prior_periods = []
            if complete:
                for history_start, history_end, values in history:
                    prior_row = values.get(key)
                    if prior_row is None or prior_row["item"]["status"] != "COMPLETE":
                        continue
                    if metric == "CONSUMPTION_VARIANCE" and prior_row["item"]["theoretical_status"] != "COMPLETE":
                        continue
                    prior_value = _metric_value(prior_row, metric)
                    if prior_value is not None:
                        prior.append(prior_value)
                        prior_periods.append({"start_date": history_start,
                            "end_date": history_end})
            baseline = Decimal(str(median(prior))) if len(prior) >= MIN_BASELINE_PERIODS else None
            mad = Decimal(str(median([abs(value - baseline) for value in prior]))) if baseline is not None else None
            delta = abs(value - baseline) if baseline is not None else None
            threshold = _threshold(metric, baseline, mad) if baseline is not None and mad is not None else None
            anomaly = delta is not None and threshold is not None and delta >= threshold
            repeats = 1
            if threshold is not None:
                for historic_value in prior:
                    if abs(historic_value - baseline) >= threshold:
                        repeats += 1
                    else:
                        break
            # No claim where underlying status is incomplete; report a separate DQ item below.
            result_status = ("INCOMPLETE_DATA" if not complete else
                "INSUFFICIENT_BASELINE" if baseline is None else "ANOMALY" if anomaly else "NORMAL")
            if result_status not in {"ANOMALY", "NORMAL", "INSUFFICIENT_BASELINE"}:
                continue
            # Zero theoretical quantity has no meaningful percentage; absolute variance still reports.
            percent = (delta / abs(baseline) * 100 if delta is not None and baseline not in (None, ZERO) else None)
            name = {"POSITIVE_ADJUSTMENT_COUNT":"POSITIVE_ADJUSTMENT_FREQUENCY",
                "NEGATIVE_ADJUSTMENT_COUNT":"NEGATIVE_ADJUSTMENT_FREQUENCY"}.get(metric, metric)
            payload = f"{company_id}:{key[0]}:{key[1]}:{name}:{start_date}:{end_date}"
            sev = _severity(delta, threshold, repeats) if anomaly and delta is not None and threshold else None
            metric_unit = item["canonical_unit"] if metric == "CONSUMPTION_VARIANCE" or unit == "quantity" else unit
            reason_codes = item["reason_codes"] + (item["theoretical_reason_codes"] if metric == "CONSUMPTION_VARIANCE" else [])
            findings.append({
                "id": str(uuid5(NAMESPACE_URL, payload)), "finding_type": name,
                "status": result_status, "severity": sev,
                "confidence": _confidence(len(prior), complete), "company_id": company_id,
                "branch_id": item["branch_id"], "branch_name": item["branch_name"],
                "ingredient_id": item["ingredient_id"], "ingredient_sku": item["ingredient_sku"],
                "ingredient_name": item["ingredient_name"], "unit": item["canonical_unit"],
                "start_date": start_date, "end_date": end_date, "metric_value": value,
                "metric_unit": metric_unit, "baseline_value": baseline, "absolute_difference": delta,
                "percentage_difference": percent,
                "direction": ("ABOVE_THEORETICAL" if value > 0 else "BELOW_THEORETICAL" if value < 0 else "ALIGNED")
                    if metric == "CONSUMPTION_VARIANCE" else
                    ("INCREASED" if baseline is not None and value > baseline else "DECREASED" if baseline is not None and value < baseline else None),
                "baseline_periods": len(prior),
                "baseline_comparison_periods": prior_periods if baseline is not None else [],
                "data_status": item["comparison_status" if metric == "CONSUMPTION_VARIANCE" else "status"],
                "reason_codes": sorted(set(reason_codes)),
                "evidence": {"actual_sales_related_consumption": item["actual_sales_related_consumption"],
                    "theoretical_consumption": item["theoretical_consumption"],
                    "variance": item["absolute_variance"], "variance_percent": item["variance_percent"],
                    "movement_quantity": value if metric_unit not in {"%", "events"} else None,
                    "adjustment_reason_codes": row["reason_codes"],
                    "baseline_periods": len(prior), "threshold": threshold},
                "explanation": ("Observed value exceeded the configured robust historical threshold. This identifies a pattern only; its cause is unknown." if anomaly else
                    "Fewer than four complete, metric-eligible historical comparison periods were available; the finding is marked insufficient baseline and is not classified as normal or anomalous." if baseline is None else
                    "Observed value did not exceed the configured robust historical threshold."),
                "recommendation": _recommendation(name) if anomaly else None,
            })
    for key, row in current_data_quality:
        item = row["item"]
        data_status = item["comparison_status"]
        finding_status = "UNAVAILABLE" if data_status == "UNAVAILABLE" else "INCOMPLETE_DATA"
        payload = f"{company_id}:{key[0]}:{key[1]}:DATA_QUALITY:{start_date}:{end_date}"
        findings.append({"id": str(uuid5(NAMESPACE_URL, payload)),
            "finding_type": "DATA_QUALITY", "status": finding_status, "severity": None,
            "confidence": "LOW", "company_id": company_id, "branch_id": item["branch_id"],
            "branch_name": item["branch_name"], "ingredient_id": item["ingredient_id"],
            "ingredient_sku": item["ingredient_sku"], "ingredient_name": item["ingredient_name"],
            "unit": item["canonical_unit"], "start_date": start_date, "end_date": end_date,
            "metric_value": None, "metric_unit": "status", "baseline_value": None,
            "absolute_difference": None, "percentage_difference": None, "direction": None, "baseline_periods": 0,
            "baseline_comparison_periods": [],
            "data_status": item["comparison_status"],
            "reason_codes": sorted(set(item["reason_codes"] + item["theoretical_reason_codes"])),
            "evidence": {"actual_status": item["status"], "theoretical_status": item["theoretical_status"]},
            "explanation": "Coverage or source quality is insufficient for a reliable operational conclusion. Missing dates are treated as incomplete, not closed days.",
            "recommendation": "Complete the relevant daily workbook coverage declarations and correct source data before interpreting operational metrics."})
    # Branch peer comparisons use the same ingredient and period. Percentages are
    # derived from company numerators/denominators only, never averaged by branch.
    for ingredient in {key[1] for key in current}:
        peers = [row for (bid, iid), row in current.items() if bid is not None
            and iid == ingredient and row["item"]["status"] == "COMPLETE"]
        if len(peers) < 3:
            continue
        peer_metrics = (("WASTE_RATE", "BRANCH_WASTE_RATE", MIN_OPERATIONAL_RATE_POINT_CHANGE),
            ("DAMAGE_RATE", "BRANCH_DAMAGE_RATE", MIN_OPERATIONAL_RATE_POINT_CHANGE),
            ("CONSUMPTION_VARIANCE_PERCENT", "BRANCH_CONSUMPTION_VARIANCE", Decimal("10")))
        for metric, finding_kind, floor in peer_metrics:
            if metric == "CONSUMPTION_VARIANCE_PERCENT":
                metric_rows = [(row, row["item"]["variance_percent"]
                    if row["item"]["theoretical_status"] == "COMPLETE" else None) for row in peers]
            else:
                metric_rows = [(row, _metric_value(row, metric)) for row in peers]
            metric_rows = [(row, value) for row, value in metric_rows if value is not None]
            if len(metric_rows) < 3:
                continue
            center = Decimal(str(median([value for _, value in metric_rows])))
            for row, value in metric_rows:
                difference = value - center
                if abs(difference) < floor:
                    continue
                item = row["item"]
                payload = f"{company_id}:{item['branch_id']}:{ingredient}:{finding_kind}:{start_date}:{end_date}"
                findings.append({"id": str(uuid5(NAMESPACE_URL, payload)), "finding_type": finding_kind,
                    "status": "ANOMALY", "severity": "LOW", "confidence": "MEDIUM",
                    "company_id": company_id, "branch_id": item["branch_id"], "branch_name": item["branch_name"],
                    "ingredient_id": ingredient, "ingredient_sku": item["ingredient_sku"],
                    "ingredient_name": item["ingredient_name"], "unit": item["canonical_unit"],
                    "start_date": start_date, "end_date": end_date, "metric_value": value,
                    "metric_unit": "%", "baseline_value": center, "absolute_difference": abs(difference),
                    "percentage_difference": None, "direction": "ABOVE_PEER_MEDIAN" if difference > 0 else "BELOW_PEER_MEDIAN",
                    "baseline_periods": len(metric_rows), "baseline_comparison_periods": [],
                    "data_status": "COMPLETE",
                    "reason_codes": [], "evidence": {"comparable_branches": len(metric_rows), "peer_median": center},
                    "explanation": f"This complete branch differs from the same-ingredient, same-period peer median by at least {floor} percentage points.",
                    "recommendation": _recommendation("WASTE" if metric == "WASTE_RATE" else "DAMAGE" if metric == "DAMAGE_RATE" else "CONSUMPTION_VARIANCE")})
    if finding_type:
        findings = [f for f in findings if f["finding_type"] == finding_type]
    if severity:
        findings = [f for f in findings if f["severity"] == severity]
    if status:
        findings = [f for f in findings if f["status"] == status]
    findings.sort(key=lambda f: (f["status"] != "ANOMALY", {"CRITICAL":0,"HIGH":1,"MEDIUM":2,"LOW":3,None:4}.get(f["severity"], 5), f["finding_type"], str(f["branch_id"]), str(f["ingredient_id"]), f["id"]))
    total = len(findings)
    return {"start_date": start_date, "end_date": end_date, "branch_id": branch_id,
        "ingredient_id": ingredient_id, "finding_type": finding_type, "severity": severity,
        "status": status, "total": total, "offset": offset, "limit": limit,
        "findings": findings[offset:offset+limit], "limitations": [
            "Initial thresholds are operational heuristics, not statistically validated business rules.",
            "Baseline needs at least four complete equal-length periods and is limited to the preceding 730 days.",
            "Current Phase 4C.5 requires a completed upload and daily coverage for every calendar date; missing dates remain incomplete.",
            "Historical v1/v2 uploads without v3 declarations cannot establish confirmed zero or complete movement coverage.",
            "Financial impact is omitted because this engine does not establish a valid period-applicable unit cost.",
            "Causes are unknown; recommendations are investigation prompts, not findings of misconduct.",
        ]}

