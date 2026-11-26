from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.models import (Branch, DailyUpload, InventorySnapshot, Product,
    PurchaseLine, PurchaseReceiptCurrentLine, StockCoverageDeclaration,
    StockMovement, StockTransfer)
from app.services.stock_movements import INFLOW_TYPES
from app.services.theoretical_consumption import calculate_theoretical_consumption
from app.services.actual_consumption_queries import load_actual_consumption_inputs
from app.core.branch_scope import BranchAccessScope


ZERO = Decimal("0")
MOVEMENT_TYPES = (
    "PURCHASE_RECEIPT", "OTHER_INFLOW", "POSITIVE_ADJUSTMENT", "TRANSFER_IN",
    "WASTE", "STAFF_CONSUMPTION", "DAMAGE", "NEGATIVE_ADJUSTMENT",
    "OTHER_OUTFLOW", "TRANSFER_OUT",
)
OUTFLOW_TYPES = set(MOVEMENT_TYPES) - INFLOW_TYPES
NON_SALES_OUTFLOW_TYPES = {
    "WASTE", "STAFF_CONSUMPTION", "DAMAGE", "NEGATIVE_ADJUSTMENT",
    "OTHER_OUTFLOW", "TRANSFER_OUT",
}
STOCK_COVERAGE_TYPES = {"COMPLETE", "NO_STOCK"}
MOVEMENT_COVERAGE_TYPES = {"COMPLETE", "NOT_APPLICABLE"}


def _decimal(value: Any) -> bool:
    return isinstance(value, Decimal) and value.is_finite()


def actual_ingredient_consumption(db, company_id: UUID, start_date: date,
        end_date: date, branch_id: UUID | None, ingredient_id: UUID | None,
        branch_scope: BranchAccessScope) -> dict:
    data = load_actual_consumption_inputs(db, company_id, start_date,
        end_date, branch_scope, ingredient_id)
    theoretical = calculate_theoretical_consumption(
        data["theoretical_scopes"], data["theoretical_sales"], company_id)
    data["theoretical_items"] = theoretical["items"]
    data["theoretical_scopes"] = theoretical["scopes"]
    return calculate_actual_consumption(data, company_id, start_date,
        end_date, branch_id, ingredient_id)


@dataclass
class _Result:
    branch: Branch
    product: Product
    status: str = "COMPLETE"
    reasons: set[str] | None = None
    opening: Decimal | None = None
    closing: Decimal | None = None
    inflows: Decimal | None = None
    outflows: Decimal | None = None
    depletion: Decimal | None = None
    non_sales: Decimal | None = None
    sales_consumption: Decimal | None = None
    theoretical: Decimal | None = None
    theoretical_status: str = "UNAVAILABLE"
    theoretical_reasons: set[str] | None = None
    source_uploads: set[tuple[UUID, int]] | None = None
    inflow_coverage_complete: bool = True
    outflow_coverage_complete: bool = True
    stock_coverage_complete: bool = True
    _transfer_in: Decimal = ZERO
    _transfer_out: Decimal = ZERO


def _status(incomplete: bool, unavailable: bool, invalid: bool,
            unit_mismatch: bool) -> str:
    if unit_mismatch:
        return "UNIT_MISMATCH"
    if invalid:
        return "INVALID_DATA"
    if unavailable:
        return "UNAVAILABLE"
    if incomplete:
        return "INCOMPLETE"
    return "COMPLETE"


def calculate_actual_consumption(data: dict, company_id: UUID,
        start_date: date, end_date: date, branch_id: UUID | None,
        ingredient_id: UUID | None) -> dict:
    """Calculate actual stock depletion, with absence represented as unknown."""
    branches: tuple[Branch, ...] = data["branches"]
    products: tuple[Product, ...] = data["products"]
    uploads: tuple[DailyUpload, ...] = data.get("uploads", ())
    current_uploads: tuple[DailyUpload, ...] = data.get("current_uploads", uploads)
    snapshots: tuple[InventorySnapshot, ...] = data.get("snapshots", ())
    declarations: tuple[StockCoverageDeclaration, ...] = data.get("declarations", ())
    purchase_lines: tuple[PurchaseLine, ...] = data.get("purchase_lines", ())
    receipt_current_lines: tuple[PurchaseReceiptCurrentLine, ...] = data.get("receipt_current_lines", ())
    movements: tuple[StockMovement, ...] = data.get("movements", ())
    transfers: tuple[StockTransfer, ...] = data.get("transfers", ())

    uploads_by_scope: dict[tuple[UUID, date], list[DailyUpload]] = defaultdict(list)
    upload_by_id: dict[UUID, DailyUpload] = {}
    for upload in uploads:
        uploads_by_scope[(upload.branch_id, upload.business_date)].append(upload)
        upload_by_id[upload.id] = upload
    # Source versions for receipts may have a business date outside the report.
    for upload in current_uploads:
        upload_by_id[upload.id] = upload

    snapshots_by_upload_product: dict[tuple[UUID, UUID], list[InventorySnapshot]] = defaultdict(list)
    for snapshot in snapshots:
        snapshots_by_upload_product[(snapshot.source_upload_id, snapshot.product_id)].append(snapshot)

    declarations_by_upload_product: dict[tuple[UUID, UUID], list[StockCoverageDeclaration]] = defaultdict(list)
    for declaration in declarations:
        declarations_by_upload_product[(declaration.source_upload_id,
            declaration.ingredient_product_id)].append(declaration)

    movements_by_branch_product_date: dict[tuple[UUID, UUID, date], list[StockMovement]] = defaultdict(list)
    movements_by_purchase_line: dict[UUID, list[StockMovement]] = defaultdict(list)
    movements_by_transfer: dict[UUID, list[StockMovement]] = defaultdict(list)
    for movement in movements:
        movements_by_branch_product_date[(movement.branch_id,
            movement.ingredient_product_id, movement.movement_date)].append(movement)
        if movement.purchase_line_id is not None:
            movements_by_purchase_line[movement.purchase_line_id].append(movement)
        if movement.transfer_id is not None:
            movements_by_transfer[movement.transfer_id].append(movement)

    purchases_by_upload_product: dict[tuple[UUID, UUID], list[PurchaseLine]] = defaultdict(list)
    for line in purchase_lines:
        purchases_by_upload_product[(line.source_upload_id, line.product_id)].append(line)

    current_line_by_identity = {line.receipt_identity_id: line.purchase_line_id
        for line in receipt_current_lines}
    invalid_transfers: dict[UUID, str] = {}
    transfer_by_id = {transfer.id: transfer for transfer in transfers}
    for transfer in transfers:
        legs = movements_by_transfer.get(transfer.id, [])
        out_legs = [leg for leg in legs if leg.movement_type == "TRANSFER_OUT"]
        in_legs = [leg for leg in legs if leg.movement_type == "TRANSFER_IN"]
        if (len(legs) != 2 or len(out_legs) != 1 or len(in_legs) != 1):
            invalid_transfers[transfer.id] = "INVALID_TRANSFER_PAIR"
            continue
        out_leg, in_leg = out_legs[0], in_legs[0]
        legs_match = (
            out_leg.company_id == transfer.company_id == in_leg.company_id
            and out_leg.ingredient_product_id == transfer.ingredient_product_id == in_leg.ingredient_product_id
            and out_leg.movement_date == transfer.movement_date == in_leg.movement_date
            and out_leg.quantity == transfer.quantity == in_leg.quantity
            and out_leg.unit == transfer.unit == in_leg.unit
            and out_leg.branch_id == transfer.source_branch_id
            and in_leg.branch_id == transfer.destination_branch_id
            and out_leg.batch_number == transfer.source_batch_number
            and in_leg.batch_number == transfer.destination_batch_number
            and out_leg.voided_at is None and in_leg.voided_at is None
        )
        if not legs_match:
            invalid_transfers[transfer.id] = "INVALID_TRANSFER_PAIR"
    for movement in movements:
        if movement.transfer_id is not None and movement.transfer_id not in transfer_by_id:
            invalid_transfers[movement.transfer_id] = "INVALID_TRANSFER_PAIR"

    days = tuple(start_date + timedelta(days=offset)
        for offset in range((end_date - start_date).days + 1))
    branch_results: list[_Result] = []

    def add_reason(result: _Result, code: str, *, invalid: bool = False,
                   unit_mismatch: bool = False) -> None:
        if result.reasons is None:
            result.reasons = set()
        result.reasons.add(code)
        if unit_mismatch:
            result.status = "UNIT_MISMATCH"
        elif invalid and result.status != "UNIT_MISMATCH":
            result.status = "INVALID_DATA"
        elif result.status == "COMPLETE":
            result.status = "INCOMPLETE"

    def declarations_for(upload: DailyUpload, product: Product) -> list[StockCoverageDeclaration]:
        rows = declarations_by_upload_product.get((upload.id, product.id), [])
        for row in rows:
            if row.unit != product.unit_of_measure:
                add_reason(active_result, "UNIT_MISMATCH", unit_mismatch=True)
        key_counts: dict[tuple, int] = defaultdict(int)
        for row in rows:
            key_counts[(row.coverage_dimension, row.scope_type, row.batch_number,
                row.movement_type)] += 1
        if any(count > 1 for count in key_counts.values()):
            add_reason(active_result, "DUPLICATE_COVERAGE_DECLARATION", invalid=True)
        by_dimension: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            by_dimension[row.coverage_dimension].add(row.scope_type)
        if any("BATCH" in scopes and ("INGREDIENT" in scopes or "ALL_BATCHES" in scopes)
                for scopes in by_dimension.values()):
            add_reason(active_result, "CONFLICTING_COVERAGE_SCOPE", invalid=True)
        return rows

    def require_daily_status(result: _Result, upload: DailyUpload,
            product: Product, declarations: list[StockCoverageDeclaration],
            dimension: str, scopes: set[str], allowed: set[str]) -> bool:
        matches = [item for item in declarations
            if item.coverage_dimension == dimension and item.scope_type in scopes]
        if len(matches) != 1:
            add_reason(result, f"MISSING_OR_CONFLICTING_{dimension}_COVERAGE",
                invalid=len(matches) > 1)
            return False
        item = matches[0]
        if item.status not in allowed:
            add_reason(result, f"{dimension}_COVERAGE_{item.status}")
            return False
        rows = snapshots_by_upload_product.get((upload.id, product.id), [])
        if item.status == "COMPLETE" and dimension in {"INGREDIENT", "BATCH"} and not rows:
            add_reason(result, f"INVALID_COMPLETE_{dimension}_COVERAGE", invalid=True)
            return False
        if item.status == "NO_STOCK":
            has_positive_snapshot = any(row.opening_quantity > 0 or row.closing_quantity > 0
                for row in rows)
            if has_positive_snapshot:
                add_reason(result, f"CONTRADICTORY_NO_STOCK_{dimension}", invalid=True)
                return False
        return True

    def category_coverage(result: _Result, upload: DailyUpload,
            product: Product, declarations: list[StockCoverageDeclaration],
            movement_type: str, known_batches: set[str], has_unbatched: bool) -> None:
        def mark_incomplete() -> None:
            if movement_type in INFLOW_TYPES:
                result.inflow_coverage_complete = False
            else:
                result.outflow_coverage_complete = False

        matches = [row for row in declarations
            if row.coverage_dimension == "MOVEMENT_CATEGORY"
            and row.movement_type == movement_type]
        broad = [row for row in matches if row.scope_type in {"INGREDIENT", "ALL_BATCHES"}]
        specific = [row for row in matches if row.scope_type == "BATCH"]
        if broad and specific or len(broad) > 1:
            add_reason(result, "CONFLICTING_MOVEMENT_COVERAGE", invalid=True)
            mark_incomplete()
            return
        if broad:
            covered = broad[0]
            if covered.status not in MOVEMENT_COVERAGE_TYPES:
                add_reason(result, f"MOVEMENT_{movement_type}_COVERAGE_{covered.status}")
                mark_incomplete()
                return
            if covered.status == "NOT_APPLICABLE":
                observed = any(row.movement_type == movement_type
                    and row.voided_at is None
                    for row in movements_by_branch_product_date.get((upload.branch_id,
                        product.id, upload.business_date), []))
                if movement_type == "PURCHASE_RECEIPT":
                    observed = observed or bool(purchases_by_upload_product.get(
                        (upload.id, product.id), []))
                if observed:
                    add_reason(result, "CONTRADICTORY_NOT_APPLICABLE_MOVEMENT", invalid=True)
                    mark_incomplete()
            return
        if specific:
            if has_unbatched or not known_batches:
                add_reason(result, f"INCOMPLETE_MOVEMENT_{movement_type}_BATCH_COVERAGE")
                mark_incomplete()
                return
            by_batch = {row.batch_number: row for row in specific}
            if not known_batches.issubset(by_batch):
                add_reason(result, f"INCOMPLETE_MOVEMENT_{movement_type}_BATCH_COVERAGE")
                mark_incomplete()
                return
            for batch in known_batches:
                if by_batch[batch].status not in MOVEMENT_COVERAGE_TYPES:
                    add_reason(result, f"MOVEMENT_{movement_type}_COVERAGE_{by_batch[batch].status}")
                    mark_incomplete()
                elif by_batch[batch].status == "NOT_APPLICABLE":
                    observed = any(row.movement_type == movement_type
                        and row.batch_number == batch and row.voided_at is None
                        for row in movements_by_branch_product_date.get(
                            (upload.branch_id, product.id, upload.business_date), []))
                    if movement_type == "PURCHASE_RECEIPT":
                        observed = observed or any(line.batch_number == batch
                            for line in purchases_by_upload_product.get(
                                (upload.id, product.id), []))
                    if observed:
                        add_reason(result, "CONTRADICTORY_NOT_APPLICABLE_MOVEMENT", invalid=True)
                        mark_incomplete()
            return
        add_reason(result, f"MISSING_MOVEMENT_{movement_type}_COVERAGE")
        mark_incomplete()

    def boundary_value(result: _Result, upload: DailyUpload, product: Product,
            declarations: list[StockCoverageDeclaration], dimension: str,
            quantity_attr: str) -> Decimal | None:
        rows = snapshots_by_upload_product.get((upload.id, product.id), [])
        grouped: dict[str, list[InventorySnapshot]] = defaultdict(list)
        for row in rows:
            grouped[row.batch_number or ""].append(row)
            if row.unit != product.unit_of_measure:
                add_reason(result, "UNIT_MISMATCH", unit_mismatch=True)
            quantity = getattr(row, quantity_attr)
            if not _decimal(quantity) or quantity < 0:
                add_reason(result, "INVALID_STOCK_QUANTITY", invalid=True)
        if any(len(group) > 1 for group in grouped.values()):
            add_reason(result, "DUPLICATE_STOCK_SNAPSHOT", invalid=True)

        matches = [row for row in declarations if row.coverage_dimension == dimension]
        broad = [row for row in matches if row.scope_type in {"INGREDIENT", "ALL_BATCHES"}]
        specific = [row for row in matches if row.scope_type == "BATCH"]
        if broad and specific or len(broad) > 1:
            add_reason(result, f"CONFLICTING_{dimension}_COVERAGE", invalid=True)
            return None
        if broad:
            declaration = broad[0]
            if declaration.status == "NO_STOCK":
                if any(getattr(row, quantity_attr) > 0 for row in rows):
                    add_reason(result, f"CONTRADICTORY_NO_STOCK_{dimension}", invalid=True)
                    return None
                return ZERO
            if declaration.status != "COMPLETE":
                add_reason(result, f"{dimension}_COVERAGE_{declaration.status}")
                return None
            if not rows:
                add_reason(result, f"INVALID_COMPLETE_{dimension}_WITHOUT_STOCK_ROWS", invalid=True)
                return None
            return sum((getattr(row, quantity_attr) for row in rows), ZERO)
        if specific:
            by_batch = {row.batch_number: row for row in specific}
            batch_universe = set(grouped) | set(by_batch)
            if not batch_universe:
                add_reason(result, f"MISSING_{dimension}_COVERAGE")
                return None
            values: list[Decimal] = []
            for batch in batch_universe:
                declaration = by_batch.get(batch)
                batch_rows = grouped.get(batch, [])
                if declaration is None:
                    add_reason(result, f"INCOMPLETE_{dimension}_BATCH_COVERAGE")
                elif declaration.status == "NO_STOCK":
                    if any(getattr(row, quantity_attr) > 0 for row in batch_rows):
                        add_reason(result, f"CONTRADICTORY_NO_STOCK_{dimension}", invalid=True)
                    else:
                        values.append(ZERO)
                elif declaration.status == "COMPLETE" and len(batch_rows) == 1:
                    values.append(getattr(batch_rows[0], quantity_attr))
                elif declaration.status == "COMPLETE" and not batch_rows:
                    add_reason(result, f"INVALID_COMPLETE_{dimension}_WITHOUT_BATCH_ROW", invalid=True)
                else:
                    add_reason(result, f"INCOMPLETE_{dimension}_BATCH_COVERAGE")
            if len(values) == len(batch_universe):
                return sum(values, ZERO)
            return None
        add_reason(result, f"MISSING_{dimension}_COVERAGE")
        return None

    def validate_daily_snapshots(result: _Result, upload: DailyUpload,
            product: Product) -> None:
        rows = snapshots_by_upload_product.get((upload.id, product.id), [])
        batches: dict[str, int] = defaultdict(int)
        for row in rows:
            batches[row.batch_number or ""] += 1
            if row.unit != product.unit_of_measure:
                add_reason(result, "UNIT_MISMATCH", unit_mismatch=True)
            for value in (row.opening_quantity, row.closing_quantity,
                          row.damaged_quantity, row.wasted_quantity):
                if not _decimal(value) or value < 0:
                    add_reason(result, "INVALID_STOCK_QUANTITY", invalid=True)
            if row.staff_consumption_quantity is not None and (
                    not _decimal(row.staff_consumption_quantity)
                    or row.staff_consumption_quantity < 0):
                add_reason(result, "INVALID_STOCK_QUANTITY", invalid=True)
            if not _decimal(row.adjustment_quantity):
                add_reason(result, "INVALID_STOCK_ADJUSTMENT", invalid=True)
                continue
            batch_movements = [movement for movement in
                movements_by_branch_product_date.get((upload.branch_id,
                    product.id, upload.business_date), [])
                if movement.voided_at is None
                and (movement.batch_number or "") == (row.batch_number or "")]
            for attribute, movement_type in (
                    ("damaged_quantity", "DAMAGE"),
                    ("wasted_quantity", "WASTE"),
                    ("staff_consumption_quantity", "STAFF_CONSUMPTION")):
                reported = getattr(row, attribute)
                # Blank legacy cells became zero in older processors; only a
                # positive stored value is reliable enough to reconcile.
                if reported is not None and reported > 0:
                    ledger_quantity = sum((movement.quantity for movement in batch_movements
                        if movement.movement_type == movement_type), ZERO)
                    if ledger_quantity != reported:
                        add_reason(result, "INVENTORY_MOVEMENT_QUANTITY_MISMATCH", invalid=True)
            if row.adjustment_quantity != ZERO:
                signed_ledger_adjustment = sum((movement.quantity
                    if movement.movement_type == "POSITIVE_ADJUSTMENT"
                    else -movement.quantity
                    for movement in batch_movements if movement.movement_type in {
                        "POSITIVE_ADJUSTMENT", "NEGATIVE_ADJUSTMENT"}), ZERO)
                if signed_ledger_adjustment != row.adjustment_quantity:
                    add_reason(result, "INVENTORY_ADJUSTMENT_MOVEMENT_MISMATCH", invalid=True)
        if any(count > 1 for count in batches.values()):
            add_reason(result, "DUPLICATE_STOCK_SNAPSHOT", invalid=True)

    for branch in branches:
        branch_uploads = uploads_by_scope
        branch_any_upload = any(upload.branch_id == branch.id for upload in uploads)
        for product in products:
            result = _Result(branch=branch, product=product,
                reasons=set(), theoretical_reasons=set(), source_uploads=set())
            branch_results.append(result)
            active_result = result
            if not branch_any_upload:
                result.status = "UNAVAILABLE"
                result.reasons.add("NO_COMPLETED_CURRENT_UPLOAD")
            daily_upload_by_date: dict[date, DailyUpload] = {}
            for day in days:
                matches = branch_uploads.get((branch.id, day), [])
                if len(matches) != 1:
                    add_reason(result, "MISSING_OR_DUPLICATE_CURRENT_COMPLETED_UPLOAD",
                        invalid=len(matches) > 1)
                    result.stock_coverage_complete = False
                    result.inflow_coverage_complete = False
                    result.outflow_coverage_complete = False
                    continue
                upload = matches[0]
                daily_upload_by_date[day] = upload
                result.source_uploads.add((upload.id, upload.version))
                decs = declarations_for(upload, product)
                validate_daily_snapshots(result, upload, product)
                if not require_daily_status(result, upload, product, decs,
                        "INGREDIENT", {"INGREDIENT"}, STOCK_COVERAGE_TYPES):
                    result.stock_coverage_complete = False
                if not require_daily_status(result, upload, product, decs,
                        "BATCH", {"ALL_BATCHES"}, STOCK_COVERAGE_TYPES):
                    result.stock_coverage_complete = False

                day_movements = [movement for movement in movements_by_branch_product_date.get(
                    (branch.id, product.id, day), []) if movement.voided_at is None]
                source_purchases = purchases_by_upload_product.get((upload.id, product.id), [])
                known_batches = {row.batch_number for row in snapshots_by_upload_product.get(
                    (upload.id, product.id), []) if row.batch_number}
                known_batches.update(row.batch_number for row in day_movements if row.batch_number)
                known_batches.update(line.batch_number for line in source_purchases if line.batch_number)
                has_unbatched = (any(not row.batch_number for row in day_movements)
                    or any(not line.batch_number for line in source_purchases)
                    or any(not row.batch_number for row in snapshots_by_upload_product.get(
                        (upload.id, product.id), [])))
                for movement_type in MOVEMENT_TYPES:
                    category_coverage(result, upload, product, decs,
                        movement_type, known_batches, has_unbatched)

            # Physical beginning and ending stock are explicit observations on
            # the first and last requested business dates, never summed daily.
            opening_upload = daily_upload_by_date.get(start_date)
            closing_upload = daily_upload_by_date.get(end_date)
            if opening_upload is not None:
                result.opening = boundary_value(result, opening_upload, product,
                    declarations_for(opening_upload, product), "OPENING_STOCK",
                    "opening_quantity")
            else:
                add_reason(result, "MISSING_OPENING_STOCK")
            if closing_upload is not None:
                result.closing = boundary_value(result, closing_upload, product,
                    declarations_for(closing_upload, product), "CLOSING_STOCK",
                    "closing_quantity")
            else:
                add_reason(result, "MISSING_CLOSING_STOCK")

            # Purchase lines are provenance only: every confirmed receipt must
            # have exactly one linked ledger movement. Only the movement enters
            # the inflow total, so the line is never counted a second time.
            for line in [line for line in purchase_lines
                    if line.branch_id == branch.id and line.product_id == product.id]:
                result.source_uploads.add((line.source_upload_id,
                    upload_by_id[line.source_upload_id].version))
                if line.purchase_unit is None:
                    add_reason(result, "PURCHASE_UNIT_UNKNOWN")
                    result.inflow_coverage_complete = False
                    continue
                if line.purchase_unit != product.unit_of_measure:
                    add_reason(result, "UNIT_MISMATCH", unit_mismatch=True)
                    result.inflow_coverage_complete = False
                    continue
                if line.receipt_identity_id is not None and current_line_by_identity.get(
                        line.receipt_identity_id) != line.id:
                    add_reason(result, "PURCHASE_RECEIPT_CURRENT_LINE_MISMATCH", invalid=True)
                    result.inflow_coverage_complete = False
                linked = movements_by_purchase_line.get(line.id, [])
                if len(linked) != 1:
                    add_reason(result, "MISSING_OR_DUPLICATE_PURCHASE_RECEIPT_MOVEMENT",
                        invalid=True)
                    result.inflow_coverage_complete = False
                    continue
                movement = linked[0]
                if (movement.movement_type != "PURCHASE_RECEIPT"
                        or movement.source_upload_id != line.source_upload_id
                        or movement.company_id != line.company_id
                        or movement.branch_id != line.branch_id
                        or movement.ingredient_product_id != line.product_id
                        or movement.movement_date != line.receipt_date
                        or movement.quantity != line.quantity_received
                        or movement.unit != product.unit_of_measure
                        or movement.batch_number != line.batch_number):
                    add_reason(result, "INVALID_PURCHASE_RECEIPT_MOVEMENT", invalid=True)
                    result.inflow_coverage_complete = False
                source_upload = upload_by_id.get(line.source_upload_id)
                if source_upload is None:
                    add_reason(result, "PURCHASE_RECEIPT_SOURCE_NOT_CURRENT", invalid=True)
                    result.inflow_coverage_complete = False
                else:
                    source_decs = declarations_for(source_upload, product)
                    category_coverage(result, source_upload, product, source_decs,
                        "PURCHASE_RECEIPT", {line.batch_number} if line.batch_number else set(),
                        not bool(line.batch_number))

            # Validate every ledger event and sum only ledger quantities.
            inflows = ZERO
            outflows = ZERO
            movement_valid = True
            transfer_out = ZERO
            for day in days:
                for movement in movements_by_branch_product_date.get(
                        (branch.id, product.id, day), []):
                    if movement.voided_at is not None:
                        if movement.origin_type == "UPLOAD":
                            add_reason(result, "UPLOAD_MOVEMENT_VOIDED", invalid=True)
                            movement_valid = False
                        continue
                    if movement.movement_type not in MOVEMENT_TYPES:
                        add_reason(result, "INVALID_MOVEMENT_TYPE", invalid=True)
                        movement_valid = False
                        continue
                    if not _decimal(movement.quantity) or movement.quantity <= 0:
                        add_reason(result, "INVALID_MOVEMENT_QUANTITY", invalid=True)
                        movement_valid = False
                        continue
                    if movement.unit != product.unit_of_measure:
                        add_reason(result, "UNIT_MISMATCH", unit_mismatch=True)
                        movement_valid = False
                        continue
                    if movement.origin_type == "UPLOAD":
                        source = upload_by_id.get(movement.source_upload_id)
                        if source is None or source.branch_id != movement.branch_id:
                            add_reason(result, "MOVEMENT_SOURCE_NOT_CURRENT_COMPLETED", invalid=True)
                            movement_valid = False
                            continue
                        result.source_uploads.add((source.id, source.version))
                    if movement.transfer_id is not None and movement.transfer_id in invalid_transfers:
                        add_reason(result, "INVALID_TRANSFER_PAIR", invalid=True)
                        movement_valid = False
                        continue
                    if movement.movement_type in INFLOW_TYPES:
                        inflows += movement.quantity
                    elif movement.movement_type in OUTFLOW_TYPES:
                        outflows += movement.quantity
                        if movement.movement_type == "TRANSFER_OUT":
                            transfer_out += movement.quantity
            if movement_valid:
                if result.inflow_coverage_complete:
                    result.inflows = inflows
                if result.outflow_coverage_complete:
                    result.outflows = outflows

            # A receipt movement may be present without its current purchase
            # line in the loaded source set only if it is outside this product's
            # eligible date range; in that case the movement itself is invalid.
            for movement in movements:
                if (movement.branch_id == branch.id and movement.ingredient_product_id == product.id
                        and movement.movement_type == "PURCHASE_RECEIPT"
                        and movement.voided_at is None
                        and movement.purchase_line_id not in {line.id for line in purchase_lines}):
                    add_reason(result, "ORPHAN_PURCHASE_RECEIPT_MOVEMENT", invalid=True)

            if (result.stock_coverage_complete
                    and result.opening is not None and result.closing is not None
                    and result.inflows is not None
                    and result.status not in {"INVALID_DATA", "UNIT_MISMATCH"}):
                result.depletion = result.opening + result.inflows - result.closing
                if result.outflows is not None and result.status == "COMPLETE":
                    result._transfer_in = sum((movement.quantity for movement in movements
                        if movement.branch_id == branch.id
                        and movement.ingredient_product_id == product.id
                        and movement.movement_date in days
                        and movement.voided_at is None
                        and movement.movement_type == "TRANSFER_IN"), ZERO)
                    result._transfer_out = sum((movement.quantity for movement in movements
                        if movement.branch_id == branch.id
                        and movement.ingredient_product_id == product.id
                        and movement.movement_date in days
                        and movement.voided_at is None
                        and movement.movement_type == "TRANSFER_OUT"), ZERO)
                    result.non_sales = sum((movement.quantity for movement in movements
                        if movement.branch_id == branch.id
                        and movement.ingredient_product_id == product.id
                        and movement.movement_date in days
                        and movement.voided_at is None
                        and movement.movement_type in NON_SALES_OUTFLOW_TYPES), ZERO)
                    result.sales_consumption = result.depletion - result.non_sales
                if result.depletion < 0 or (result.sales_consumption is not None
                        and result.sales_consumption < 0):
                    add_reason(result, "NEGATIVE_RECONCILED_CONSUMPTION", invalid=True)
                    result.depletion = result.sales_consumption = result.non_sales = None
            _theoretical_for_result(result, data, start_date, end_date)

    branch_items = [_to_item(result, company_id) for result in branch_results]
    company_items: list[dict] = []
    if branch_id is None:
        for product in products:
            rows = [result for result in branch_results if result.product.id == product.id]
            if rows:
                company_items.append(_company_total(rows, company_id))
    return {"items": branch_items, "company_totals": company_items}


def _theoretical_for_result(result: _Result, data: dict,
        start_date: date, end_date: date) -> None:
    scopes = [scope for scope in data.get("theoretical_scopes", ())
        if scope["branch_id"] == result.branch.id]
    scope_by_date = {scope["business_date"]: scope for scope in scopes}
    days = tuple(start_date + timedelta(days=offset)
        for offset in range((end_date - start_date).days + 1))
    reasons: set[str] = set()
    statuses: list[str] = []
    for day in days:
        scope = scope_by_date.get(day)
        if scope is None:
            reasons.add("THEORETICAL_SCOPE_MISSING")
            statuses.append("INCOMPLETE")
        else:
            statuses.append(scope["status"])
            reasons.update(scope["reason_codes"])
    theory_items = [item for item in data.get("theoretical_items", ())
        if item["branch_id"] == result.branch.id
        and item["ingredient_id"] == result.product.id]
    for item in theory_items:
        reasons.update(item["reason_codes"])
        statuses.append(item["status"])
    if any(status == "UNIT_MISMATCH" for status in statuses):
        result.theoretical_status = "UNIT_MISMATCH"
    elif any(status == "INVALID_DATA" for status in statuses):
        result.theoretical_status = "INVALID_DATA"
    elif not scopes or any(status == "UNAVAILABLE" for status in statuses):
        result.theoretical_status = "UNAVAILABLE"
        reasons.add("THEORETICAL_CONSUMPTION_UNAVAILABLE")
    elif any(status != "COMPLETE" for status in statuses):
        result.theoretical_status = "INCOMPLETE"
    else:
        values = [item["total_theoretical_consumption"] for item in theory_items]
        if any(value is None for value in values):
            result.theoretical_status = "INCOMPLETE"
            reasons.add("THEORETICAL_TOTAL_UNAVAILABLE")
        else:
            result.theoretical = sum(values, ZERO)
            result.theoretical_status = "COMPLETE"
    result.theoretical_reasons = reasons


def _comparison(actual: Decimal | None, theory: Decimal | None) -> tuple[Decimal | None, Decimal | None]:
    if actual is None or theory is None:
        return None, None
    variance = actual - theory
    percentage = (variance / theory * Decimal("100")) if theory != ZERO else None
    return variance, percentage


def _to_item(result: _Result, company_id: UUID) -> dict:
    variance, percentage = _comparison(result.sales_consumption, result.theoretical)
    reasons = result.reasons or set()
    return {
        "company_id": company_id,
        "branch_id": result.branch.id,
        "branch_name": result.branch.name,
        "ingredient_id": result.product.id,
        "ingredient_sku": result.product.sku,
        "ingredient_name": result.product.product_name,
        "canonical_unit": result.product.unit_of_measure,
        "opening_stock": result.opening,
        "closing_stock": result.closing,
        "total_inflows": result.inflows,
        "total_outflows": result.outflows,
        "actual_stock_depletion": result.depletion,
        "known_non_sales_outflows": result.non_sales,
        "actual_sales_related_consumption": result.sales_consumption,
        "theoretical_consumption": result.theoretical,
        "absolute_variance": variance,
        "variance_percent": percentage,
        "status": result.status,
        "theoretical_status": result.theoretical_status,
        "comparison_status": ("COMPLETE" if result.status == "COMPLETE"
            and result.theoretical_status == "COMPLETE" else
            result.status if result.status != "COMPLETE" else result.theoretical_status),
        "reason_codes": sorted(reasons),
        "theoretical_reason_codes": sorted(result.theoretical_reasons or set()),
        "source_uploads": [{"upload_id": upload_id, "version": version}
            for upload_id, version in sorted(result.source_uploads or set(),
                key=lambda row: (str(row[0]), row[1]))],
    }


def _company_total(rows: list[_Result], company_id: UUID) -> dict:
    first = rows[0]
    actual_status = _status(
        incomplete=any(row.status != "COMPLETE" for row in rows)
            and not all(row.status == "UNAVAILABLE" for row in rows),
        unavailable=all(row.status == "UNAVAILABLE" for row in rows),
        invalid=any(row.status == "INVALID_DATA" for row in rows),
        unit_mismatch=any(row.status == "UNIT_MISMATCH" for row in rows),
    )
    theoretical_status = _status(
        incomplete=any(row.theoretical_status != "COMPLETE" for row in rows)
            and not all(row.theoretical_status == "UNAVAILABLE" for row in rows),
        unavailable=all(row.theoretical_status == "UNAVAILABLE" for row in rows),
        invalid=any(row.theoretical_status == "INVALID_DATA" for row in rows),
        unit_mismatch=any(row.theoretical_status == "UNIT_MISMATCH" for row in rows),
    )
    source_uploads = set().union(*(row.source_uploads or set() for row in rows))
    complete = actual_status == "COMPLETE"
    opening = sum((row.opening for row in rows if row.opening is not None), ZERO) if complete else None
    closing = sum((row.closing for row in rows if row.closing is not None), ZERO) if complete else None
    # Company totals exclude paired internal transfer legs; branch rows retain
    # both legs and their operational impact.
    inflows = (sum((row.inflows for row in rows if row.inflows is not None), ZERO)
        - sum((row._transfer_in for row in rows), ZERO)) if complete else None
    outflows = (sum((row.outflows for row in rows if row.outflows is not None), ZERO)
        - sum((row._transfer_out for row in rows), ZERO)) if complete else None
    depletion = opening + inflows - closing if complete else None
    non_sales = (sum((row.non_sales or ZERO for row in rows), ZERO)
        - sum((row._transfer_out for row in rows), ZERO)) if complete else None
    actual_sales = depletion - non_sales if complete else None
    theory = sum((row.theoretical for row in rows if row.theoretical is not None), ZERO)
    if theoretical_status != "COMPLETE":
        theory = None
    variance, percentage = _comparison(actual_sales, theory)
    actual_reasons = set().union(*(row.reasons or set() for row in rows))
    theory_reasons = set().union(*(row.theoretical_reasons or set() for row in rows))
    return {
        "company_id": company_id, "branch_id": None, "branch_name": None,
        "ingredient_id": first.product.id,
        "ingredient_sku": first.product.sku,
        "ingredient_name": first.product.product_name,
        "canonical_unit": first.product.unit_of_measure,
        "opening_stock": opening, "closing_stock": closing,
        "total_inflows": inflows, "total_outflows": outflows,
        "actual_stock_depletion": depletion,
        "known_non_sales_outflows": non_sales,
        "actual_sales_related_consumption": actual_sales,
        "theoretical_consumption": theory,
        "absolute_variance": variance, "variance_percent": percentage,
        "status": actual_status, "theoretical_status": theoretical_status,
        "comparison_status": "COMPLETE" if actual_status == theoretical_status == "COMPLETE" else
            actual_status if actual_status != "COMPLETE" else theoretical_status,
        "reason_codes": sorted(actual_reasons),
        "theoretical_reason_codes": sorted(theory_reasons),
        "source_uploads": [{"upload_id": upload_id, "version": version}
            for upload_id, version in sorted(source_uploads,
                key=lambda row: (str(row[0]), row[1]))],
    }
