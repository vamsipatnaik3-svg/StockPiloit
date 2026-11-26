import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.branch_scope import BranchAccessScope, resolve_branch_scope
from app.models import (Branch, CompanyMembership, DailyUpload,
    Product, PurchaseLine, PurchaseReceiptConfirmation, PurchaseReceiptCurrentLine,
    PurchaseReceiptIdentity, StockCountLine, StockCountSubmission, StockMovement,
    StockMovementReasonCode, User)
from app.schemas.staff_operations import StockCountCreate, WasteDamageCreate
from app.services.stock_movements import _movement_query, _view


def _http(status_code: int, detail: str):
    raise HTTPException(status_code=status_code, detail=detail)


def _require_roles(membership: CompanyMembership, roles: set[str]) -> None:
    if membership.role not in roles:
        _http(403, "You do not have permission to use this operational workflow.")


def _authorized_branch(db: Session, membership: CompanyMembership,
                       branch_id: UUID, *, active_required: bool = False) -> tuple[Branch, BranchAccessScope]:
    if membership.role not in {"OWNER", "MANAGER", "STAFF"}:
        _http(403, "You do not have permission to use operational workflows.")
    scope = resolve_branch_scope(db, membership, [branch_id])
    branch_query = select(Branch).where(Branch.id == branch_id,
        Branch.company_id == membership.company_id)
    if active_required:
        branch_query = branch_query.where(Branch.is_active.is_(True))
    branch = db.scalar(branch_query)
    if branch is None:
        _http(404, "Branch not found.")
    return branch, scope


def _operational_scope(db: Session, membership: CompanyMembership,
                       branch_id: UUID | None) -> BranchAccessScope:
    if membership.role not in {"OWNER", "MANAGER", "STAFF"}:
        _http(403, "You do not have permission to use operational workflows.")
    return resolve_branch_scope(db, membership, [branch_id] if branch_id else None)


def _count_hash(data: StockCountCreate) -> str:
    payload = {
        "counted_at": data.counted_at.astimezone(timezone.utc).isoformat(),
        "corrects_submission_id": str(data.corrects_submission_id) if data.corrects_submission_id else None,
        "lines": sorted([
            {"ingredient_product_id": str(line.ingredient_product_id),
             "quantity": format(line.quantity.normalize(), "f"), "unit": line.unit,
             "batch_number": line.batch_number or ""}
            for line in data.lines
        ], key=lambda line: (line["ingredient_product_id"], line["batch_number"])),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _stored_timestamp_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    # PostgreSQL returns the timezone for this column. SQLite test sessions
    # discard tzinfo, although the inserted value is already normalized to UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _waste_request_matches(existing: StockMovement, data: WasteDamageCreate,
                           occurred_at: datetime, local_date: date,
                           product: Product) -> bool:
    return (existing.ingredient_product_id == product.id
        and existing.movement_type == data.movement_type
        and existing.quantity == data.quantity
        and existing.unit == product.unit_of_measure
        and existing.movement_date == local_date
        and _stored_timestamp_utc(existing.occurred_at) == occurred_at
        and existing.batch_number == data.batch_number
        and existing.reason_code == data.reason_code
        and existing.reason_detail == data.notes)


def _count_rows(db: Session, submission_id: UUID):
    return db.execute(select(StockCountLine, Product.sku, Product.product_name).join(
        Product, (Product.id == StockCountLine.ingredient_product_id)
        & (Product.company_id == StockCountLine.company_id),
    ).where(StockCountLine.submission_id == submission_id).order_by(
        Product.sku, StockCountLine.batch_number, StockCountLine.id)).all()


def _count_view(db: Session, submission: StockCountSubmission) -> dict:
    branch, submitter = db.execute(select(Branch, CompanyMembership).join(
        CompanyMembership, CompanyMembership.id == submission.submitted_by_membership_id,
    ).where(Branch.id == submission.branch_id,
        Branch.company_id == submission.company_id)).one()
    actor = db.get(User, submitter.user_id)
    rows = _count_rows(db, submission.id)
    return {
        "id": submission.id, "company_id": submission.company_id,
        "branch_id": submission.branch_id, "branch_name": branch.name,
        "submitted_by_membership_id": submission.submitted_by_membership_id,
        "submitted_by_name": actor.full_name if actor else "",
        "counted_at": submission.counted_at, "submitted_at": submission.submitted_at,
        "status": "SUBMITTED", "corrects_submission_id": submission.corrects_submission_id,
        "lines": [{"id": row.id, "ingredient_product_id": row.ingredient_product_id,
            "sku": sku, "ingredient_name": name, "quantity": row.quantity,
            "unit": row.unit, "batch_number": row.batch_number or None}
            for row, sku, name in rows],
    }


def create_stock_count(db: Session, membership: CompanyMembership,
                       data: StockCountCreate) -> tuple[dict, bool]:
    _require_roles(membership, {"OWNER", "STAFF"})
    _authorized_branch(db, membership, data.branch_id, active_required=True)
    request_hash = _count_hash(data)
    existing = db.scalar(select(StockCountSubmission).where(
        StockCountSubmission.company_id == membership.company_id,
        StockCountSubmission.branch_id == data.branch_id,
        StockCountSubmission.idempotency_key == data.idempotency_key,
    ))
    if existing is not None:
        if existing.request_hash != request_hash:
            _http(409, "Idempotency key was already used for a different stock count.")
        return _count_view(db, existing), False

    if data.corrects_submission_id is not None:
        original = db.scalar(select(StockCountSubmission).where(
            StockCountSubmission.id == data.corrects_submission_id,
            StockCountSubmission.company_id == membership.company_id,
            StockCountSubmission.branch_id == data.branch_id,
        ))
        if original is None:
            _http(404, "Stock count submission to correct was not found.")

    products = {}
    for line in data.lines:
        product = db.scalar(select(Product).where(
            Product.id == line.ingredient_product_id,
            Product.company_id == membership.company_id,
        ))
        if product is None:
            _http(404, "Ingredient not found.")
        if not product.is_active or product.product_kind != "INGREDIENT":
            _http(422, "Only active INGREDIENT products can be counted.")
        if line.unit != product.unit_of_measure:
            _http(422, f"Unit must exactly match the ingredient's canonical unit '{product.unit_of_measure}'.")
        products[line.ingredient_product_id] = product

    submission = StockCountSubmission(id=uuid4(), company_id=membership.company_id,
        branch_id=data.branch_id, submitted_by_membership_id=membership.id,
        idempotency_key=data.idempotency_key, request_hash=request_hash,
        counted_at=data.counted_at.astimezone(timezone.utc),
        corrects_submission_id=data.corrects_submission_id)
    db.add(submission)
    for line in data.lines:
        db.add(StockCountLine(submission_id=submission.id,
            company_id=membership.company_id, branch_id=data.branch_id,
            ingredient_product_id=line.ingredient_product_id,
            quantity=line.quantity, unit=products[line.ingredient_product_id].unit_of_measure,
            batch_number=line.batch_number or ""))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        repeated = db.scalar(select(StockCountSubmission).where(
            StockCountSubmission.company_id == membership.company_id,
            StockCountSubmission.branch_id == data.branch_id,
            StockCountSubmission.idempotency_key == data.idempotency_key,
        ))
        if repeated is not None and repeated.request_hash == request_hash:
            return _count_view(db, repeated), False
        _http(409, "Stock count conflicts with an existing submission or correction.")
    db.refresh(submission)
    return _count_view(db, submission), True


def list_stock_counts(db: Session, membership: CompanyMembership, *,
                      branch_id: UUID | None, start_at: datetime | None,
                      end_at: datetime | None, limit: int, offset: int) -> dict:
    _require_roles(membership, {"OWNER", "STAFF"})
    scope = _operational_scope(db, membership, branch_id)
    filters = [StockCountSubmission.company_id == membership.company_id,
        StockCountSubmission.branch_id.in_(scope.branch_ids)]
    if start_at is not None:
        filters.append(StockCountSubmission.counted_at >= start_at.astimezone(timezone.utc))
    if end_at is not None:
        filters.append(StockCountSubmission.counted_at <= end_at.astimezone(timezone.utc))
    total = db.scalar(select(func.count()).select_from(StockCountSubmission).where(*filters)) or 0
    submissions = db.scalars(select(StockCountSubmission).where(*filters).order_by(
        StockCountSubmission.counted_at.desc(), StockCountSubmission.id).limit(limit).offset(offset)).all()
    return {"items": [_count_view(db, item) for item in submissions],
        "total": total, "limit": limit, "offset": offset}


def get_stock_count(db: Session, membership: CompanyMembership,
                    submission_id: UUID) -> dict:
    _require_roles(membership, {"OWNER", "STAFF"})
    submission = db.scalar(select(StockCountSubmission).where(
        StockCountSubmission.id == submission_id,
        StockCountSubmission.company_id == membership.company_id,
    ))
    if submission is None:
        _http(404, "Stock count submission not found.")
    _authorized_branch(db, membership, submission.branch_id)
    return _count_view(db, submission)


def record_waste_damage(db: Session, membership: CompanyMembership,
                        data: WasteDamageCreate) -> tuple[dict, bool]:
    if data.movement_type not in {"WASTE", "DAMAGE"} or data.quantity <= 0:
        _http(422, "Only positive WASTE or DAMAGE events can be recorded.")
    branch, _ = _authorized_branch(db, membership, data.branch_id, active_required=True)
    product = db.scalar(select(Product).where(Product.id == data.ingredient_product_id,
        Product.company_id == membership.company_id))
    if product is None:
        _http(404, "Ingredient not found.")
    if not product.is_active or product.product_kind != "INGREDIENT":
        _http(422, "Only active INGREDIENT products can be used for waste or damage events.")
    if data.unit != product.unit_of_measure:
        _http(422, f"Unit must exactly match the ingredient's canonical unit '{product.unit_of_measure}'.")
    reason = db.get(StockMovementReasonCode, (data.reason_code, data.movement_type))
    if reason is None or not reason.is_active:
        _http(422, "Reason code is not active for this movement type.")
    try:
        local_date = data.occurred_at.astimezone(ZoneInfo(branch.timezone)).date()
    except (ZoneInfoNotFoundError, ValueError):
        _http(422, "Branch timezone is invalid.")
    occurred_at = data.occurred_at.astimezone(timezone.utc)
    event_id = data.idempotency_key
    existing = db.scalar(select(StockMovement).where(
        StockMovement.company_id == membership.company_id,
        StockMovement.branch_id == branch.id,
        StockMovement.physical_event_id == event_id,
    ))
    if existing is not None:
        if not _waste_request_matches(existing, data, occurred_at, local_date, product):
            _http(409, "Idempotency key was already used for a different waste or damage event.")
        row = db.execute(_movement_query().where(StockMovement.id == existing.id)).one()
        return _view(row), False

    movement = StockMovement(company_id=membership.company_id,
        branch_id=branch.id, ingredient_product_id=product.id,
        movement_date=local_date, occurred_at=occurred_at,
        movement_type=data.movement_type, quantity=data.quantity,
        unit=product.unit_of_measure, batch_number=data.batch_number,
        source_upload_id=None, purchase_line_id=None, transfer_id=None,
        origin_type="MANUAL", physical_event_id=event_id,
        source_reference=str(event_id), reason_code=reason.code,
        reason_detail=data.notes, created_by_user_id=membership.user_id)
    db.add(movement)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(StockMovement).where(
            StockMovement.company_id == membership.company_id,
            StockMovement.branch_id == branch.id,
            StockMovement.physical_event_id == event_id,
        ))
        if existing is not None and _waste_request_matches(
                existing, data, occurred_at, local_date, product):
            return _view(db.execute(_movement_query().where(
                StockMovement.id == existing.id)).one()), False
        _http(409, "Waste or damage event conflicts with existing data.")
    db.refresh(movement)
    return _view(db.execute(_movement_query().where(
        StockMovement.id == movement.id)).one()), True


def list_waste_damage(db: Session, membership: CompanyMembership, *,
                      branch_id: UUID | None, start_date: date | None,
                      end_date: date | None, limit: int, offset: int) -> dict:
    scope = _operational_scope(db, membership, branch_id)
    filters = [StockMovement.company_id == membership.company_id,
        StockMovement.branch_id.in_(scope.branch_ids),
        StockMovement.movement_type.in_(["WASTE", "DAMAGE"])]
    if start_date is not None:
        filters.append(StockMovement.movement_date >= start_date)
    if end_date is not None:
        filters.append(StockMovement.movement_date <= end_date)
    total = db.scalar(select(func.count()).select_from(StockMovement).where(*filters)) or 0
    rows = db.execute(_movement_query().where(*filters).order_by(
        StockMovement.occurred_at.desc().nullslast(), StockMovement.created_at.desc(),
        StockMovement.id).limit(limit).offset(offset)).all()
    return {"items": [_view(row) for row in rows], "total": total,
        "limit": limit, "offset": offset}


def get_waste_damage(db: Session, membership: CompanyMembership,
                     movement_id: UUID) -> dict:
    row = db.execute(_movement_query().where(
        StockMovement.id == movement_id,
        StockMovement.company_id == membership.company_id,
        StockMovement.movement_type.in_(["WASTE", "DAMAGE"]),
    )).one_or_none()
    if row is None:
        _http(404, "Waste or damage event not found.")
    _authorized_branch(db, membership, row[0].branch_id)
    return _view(row)


def _confirmation_view(db: Session, confirmation: PurchaseReceiptConfirmation) -> dict:
    identity = db.get(PurchaseReceiptIdentity, confirmation.receipt_identity_id)
    line = db.get(PurchaseLine, confirmation.purchase_line_id)
    product = db.get(Product, line.product_id)
    branch = db.get(Branch, confirmation.branch_id)
    membership = db.get(CompanyMembership, confirmation.confirmed_by_membership_id)
    user = db.get(User, membership.user_id) if membership else None
    return {"id": confirmation.id, "company_id": confirmation.company_id,
        "branch_id": confirmation.branch_id, "branch_name": branch.name,
        "receipt_identity_id": confirmation.receipt_identity_id,
        "purchase_line_id": confirmation.purchase_line_id,
        "receipt_event_id": identity.receipt_event_id,
        "ingredient_product_id": product.id, "ingredient_sku": product.sku,
        "ingredient_name": product.product_name,
        "quantity_confirmed": confirmation.quantity_confirmed,
        "unit": confirmation.unit,
        "confirmed_by_membership_id": confirmation.confirmed_by_membership_id,
        "confirmed_by_name": user.full_name if user else "",
        "confirmed_at": confirmation.confirmed_at}


def confirm_purchase_receipt(db: Session, membership: CompanyMembership,
                             receipt_identity_id: UUID, idempotency_key: UUID
                             ) -> tuple[dict, bool]:
    _require_roles(membership, {"OWNER", "STAFF"})
    identity = db.scalar(select(PurchaseReceiptIdentity).where(
        PurchaseReceiptIdentity.id == receipt_identity_id,
        PurchaseReceiptIdentity.company_id == membership.company_id))
    if identity is None:
        _http(404, "Purchase receipt not found.")
    branch, _ = _authorized_branch(db, membership, identity.branch_id,
        active_required=True)
    replay = db.scalar(select(PurchaseReceiptConfirmation).where(
        PurchaseReceiptConfirmation.company_id == membership.company_id,
        PurchaseReceiptConfirmation.branch_id == branch.id,
        PurchaseReceiptConfirmation.idempotency_key == idempotency_key,
    ))
    if replay is not None:
        if replay.receipt_identity_id != identity.id:
            _http(409, "Idempotency key was already used for another receipt.")
        return _confirmation_view(db, replay), False

    current = db.execute(select(PurchaseReceiptCurrentLine, PurchaseLine, DailyUpload, Product)
        .join(PurchaseLine, (PurchaseLine.id == PurchaseReceiptCurrentLine.purchase_line_id)
            & (PurchaseLine.receipt_identity_id == PurchaseReceiptCurrentLine.receipt_identity_id))
        .join(DailyUpload, (DailyUpload.id == PurchaseLine.source_upload_id)
            & (DailyUpload.company_id == PurchaseLine.company_id)
            & (DailyUpload.branch_id == PurchaseLine.branch_id))
        .join(Product, (Product.id == PurchaseLine.product_id)
            & (Product.company_id == PurchaseLine.company_id))
        .where(PurchaseReceiptCurrentLine.receipt_identity_id == identity.id,
            PurchaseReceiptCurrentLine.company_id == membership.company_id,
            PurchaseReceiptCurrentLine.branch_id == branch.id,
            DailyUpload.is_current.is_(True), DailyUpload.processing_status == "COMPLETED")
    ).one_or_none()
    if current is None:
        _http(409, "Only a receipt line in the current completed upload can be confirmed.")
    _, line, _, product = current
    if not product.is_active or product.product_kind != "INGREDIENT":
        _http(422, "Receipt product must be an active INGREDIENT.")
    if line.purchase_unit != product.unit_of_measure:
        _http(422, "Receipt line does not use the ingredient's canonical unit.")
    existing = db.scalar(select(PurchaseReceiptConfirmation).where(
        PurchaseReceiptConfirmation.purchase_line_id == line.id))
    if existing is not None:
        return _confirmation_view(db, existing), False

    confirmation = PurchaseReceiptConfirmation(company_id=membership.company_id,
        branch_id=branch.id, receipt_identity_id=identity.id,
        purchase_line_id=line.id, confirmed_by_membership_id=membership.id,
        ingredient_product_id=product.id,
        idempotency_key=idempotency_key,
        quantity_confirmed=line.quantity_received, unit=product.unit_of_measure)
    db.add(confirmation)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(PurchaseReceiptConfirmation).where(
            PurchaseReceiptConfirmation.purchase_line_id == line.id))
        if existing is not None:
            return _confirmation_view(db, existing), False
        _http(409, "Receipt confirmation conflicts with existing data.")
    db.refresh(confirmation)
    return _confirmation_view(db, confirmation), True


def list_receipt_confirmations(db: Session, membership: CompanyMembership, *,
                               branch_id: UUID | None, start_at: datetime | None,
                               end_at: datetime | None, limit: int, offset: int) -> dict:
    _require_roles(membership, {"OWNER", "STAFF"})
    scope = _operational_scope(db, membership, branch_id)
    filters = [PurchaseReceiptConfirmation.company_id == membership.company_id,
        PurchaseReceiptConfirmation.branch_id.in_(scope.branch_ids)]
    if start_at is not None:
        filters.append(PurchaseReceiptConfirmation.confirmed_at >= start_at.astimezone(timezone.utc))
    if end_at is not None:
        filters.append(PurchaseReceiptConfirmation.confirmed_at <= end_at.astimezone(timezone.utc))
    total = db.scalar(select(func.count()).select_from(PurchaseReceiptConfirmation).where(*filters)) or 0
    rows = db.scalars(select(PurchaseReceiptConfirmation).where(*filters).order_by(
        PurchaseReceiptConfirmation.confirmed_at.desc(),
        PurchaseReceiptConfirmation.id).limit(limit).offset(offset)).all()
    return {"items": [_confirmation_view(db, row) for row in rows],
        "total": total, "limit": limit, "offset": offset}


def list_confirmable_receipts(db: Session, membership: CompanyMembership, *,
                              branch_id: UUID | None, limit: int, offset: int) -> dict:
    _require_roles(membership, {"OWNER", "STAFF"})
    scope = _operational_scope(db, membership, branch_id)
    filters = [PurchaseReceiptCurrentLine.company_id == membership.company_id,
        PurchaseReceiptCurrentLine.branch_id.in_(scope.branch_ids),
        DailyUpload.company_id == membership.company_id,
        DailyUpload.branch_id == PurchaseReceiptCurrentLine.branch_id,
        DailyUpload.is_current.is_(True), DailyUpload.processing_status == "COMPLETED",
        Product.company_id == membership.company_id,
        Product.product_kind == "INGREDIENT", Product.is_active.is_(True),
        PurchaseLine.purchase_unit == Product.unit_of_measure]
    base = select(PurchaseReceiptCurrentLine, PurchaseLine, DailyUpload,
        Product, PurchaseReceiptIdentity, PurchaseReceiptConfirmation).join(
        PurchaseLine, (PurchaseLine.id == PurchaseReceiptCurrentLine.purchase_line_id)
            & (PurchaseLine.receipt_identity_id == PurchaseReceiptCurrentLine.receipt_identity_id)
    ).join(DailyUpload, (DailyUpload.id == PurchaseLine.source_upload_id)
        & (DailyUpload.branch_id == PurchaseLine.branch_id)
    ).join(Product, (Product.id == PurchaseLine.product_id)
        & (Product.company_id == PurchaseLine.company_id)
    ).join(PurchaseReceiptIdentity,
        PurchaseReceiptIdentity.id == PurchaseReceiptCurrentLine.receipt_identity_id
    ).outerjoin(PurchaseReceiptConfirmation,
        PurchaseReceiptConfirmation.purchase_line_id == PurchaseLine.id
    ).where(*filters)
    pending = base.where(PurchaseReceiptConfirmation.id.is_(None))
    rows = db.execute(pending.order_by(PurchaseLine.receipt_date.desc(),
        PurchaseReceiptIdentity.receipt_event_id, PurchaseLine.id)
        .offset(offset).limit(limit)).all()
    items = [{"receipt_identity_id": identity.id,
        "receipt_event_id": identity.receipt_event_id, "purchase_line_id": line.id,
        "branch_id": line.branch_id, "receipt_date": line.receipt_date,
        "ingredient_product_id": product.id, "ingredient_sku": product.sku,
        "ingredient_name": product.product_name,
        "quantity_received": line.quantity_received, "unit": product.unit_of_measure,
        "batch_number": line.batch_number,
        "confirmation_id": confirmation.id if confirmation else None}
        for _, line, _, product, identity, confirmation in rows]
    total = db.scalar(select(func.count()).select_from(pending.order_by(None).subquery())) or 0
    return {"items": items, "total": total,
        "limit": limit, "offset": offset}


def get_receipt_confirmation(db: Session, membership: CompanyMembership,
                              confirmation_id: UUID) -> dict:
    _require_roles(membership, {"OWNER", "STAFF"})
    confirmation = db.scalar(select(PurchaseReceiptConfirmation).where(
        PurchaseReceiptConfirmation.id == confirmation_id,
        PurchaseReceiptConfirmation.company_id == membership.company_id))
    if confirmation is None:
        _http(404, "Receipt confirmation not found.")
    _authorized_branch(db, membership, confirmation.branch_id)
    return _confirmation_view(db, confirmation)
