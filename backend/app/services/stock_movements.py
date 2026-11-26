from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.models import (Branch, BranchMembership, CompanyMembership, Product,
    StockMovement, StockMovementReasonCode, User)
from app.schemas.stock_movement import ManualMovementCreate


INFLOW_TYPES = {"PURCHASE_RECEIPT", "OTHER_INFLOW", "POSITIVE_ADJUSTMENT", "TRANSFER_IN"}


class MovementApiError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


def _authorize_branch(db: Session, membership: CompanyMembership, branch_id: UUID,
                      *, require_active: bool = False) -> Branch:
    if membership.role not in {"OWNER", "MANAGER", "STAFF"}:
        raise MovementApiError(403, "You do not have access to this branch.")
    query = select(Branch).where(Branch.id == branch_id,
        Branch.company_id == membership.company_id)
    if require_active:
        query = query.where(Branch.is_active.is_(True))
    branch = db.scalar(query)
    if branch is None:
        raise MovementApiError(404, "Branch not found.")
    if membership.role in {"MANAGER", "STAFF"} and db.scalar(select(BranchMembership.id).where(
        BranchMembership.branch_id == branch.id,
        BranchMembership.company_membership_id == membership.id,
    )) is None:
        raise MovementApiError(403, "You do not have access to this branch.")
    return branch


def _movement_query():
    creator = aliased(User)
    voider = aliased(User)
    return select(StockMovement, Branch.name, Product.sku, Product.product_name,
        StockMovementReasonCode.label, creator.full_name, voider.full_name).join(
        Branch, Branch.id == StockMovement.branch_id).join(
        Product, Product.id == StockMovement.ingredient_product_id).outerjoin(
        StockMovementReasonCode, (StockMovementReasonCode.code == StockMovement.reason_code)
        & (StockMovementReasonCode.movement_type == StockMovement.movement_type)).outerjoin(
        creator, creator.id == StockMovement.created_by_user_id).outerjoin(
        voider, voider.id == StockMovement.voided_by_user_id)


def _view(row) -> dict:
    movement, branch_name, sku, product_name, reason_label, creator_name, voider_name = row
    return {
        "id": movement.id,
        "company_id": movement.company_id,
        "branch_id": movement.branch_id,
        "branch_name": branch_name,
        "ingredient_product_id": movement.ingredient_product_id,
        "ingredient_sku": sku,
        "ingredient_name": product_name,
        "movement_type": movement.movement_type,
        "direction": "INFLOW" if movement.movement_type in INFLOW_TYPES else "OUTFLOW",
        "movement_date": movement.movement_date,
        "occurred_at": movement.occurred_at,
        "quantity": movement.quantity,
        "unit": movement.unit,
        "batch_number": movement.batch_number,
        "origin_type": movement.origin_type,
        "source_upload_id": movement.source_upload_id,
        "purchase_line_id": movement.purchase_line_id,
        "transfer_id": movement.transfer_id,
        "source_reference": movement.source_reference,
        "reason_code": movement.reason_code,
        "reason_label": reason_label,
        "reason_detail": movement.reason_detail,
        "created_by_user_id": movement.created_by_user_id,
        "created_by_name": creator_name,
        "created_at": movement.created_at,
        "voided_by_user_id": movement.voided_by_user_id,
        "voided_by_name": voider_name,
        "voided_at": movement.voided_at,
        "void_reason": movement.void_reason,
    }


def create_manual_movement(db: Session, membership: CompanyMembership,
                           data: ManualMovementCreate) -> dict:
    if membership.role not in {"OWNER", "MANAGER"}:
        raise MovementApiError(403, "You do not have permission to create this stock movement.")
    branch = _authorize_branch(db, membership, data.branch_id, require_active=True)
    product = db.scalar(select(Product).where(
        Product.id == data.ingredient_product_id,
        Product.company_id == membership.company_id,
    ))
    if product is None:
        raise MovementApiError(404, "Ingredient not found.")
    if not product.is_active:
        raise MovementApiError(422, "Inactive ingredients cannot be used for stock movements.")
    if product.product_kind != "INGREDIENT":
        raise MovementApiError(422, "Product must be classified as INGREDIENT.")
    if data.unit != product.unit_of_measure:
        raise MovementApiError(422, f"Unit must exactly match the ingredient's canonical unit '{product.unit_of_measure}'.")

    reason = db.get(StockMovementReasonCode, (data.reason_code, data.movement_type))
    if reason is None or not reason.is_active:
        raise MovementApiError(422, "Reason code is not active for this movement type.")

    movement = StockMovement(
        company_id=membership.company_id,
        branch_id=branch.id,
        ingredient_product_id=product.id,
        movement_date=data.movement_date,
        movement_type=data.movement_type,
        quantity=data.quantity,
        unit=product.unit_of_measure,
        batch_number=data.batch_number,
        source_upload_id=None,
        purchase_line_id=None,
        transfer_id=None,
        origin_type="MANUAL",
        physical_event_id=uuid4(),
        source_reference=data.source_reference,
        reason_code=reason.code,
        reason_detail=data.reason_detail,
        created_by_user_id=membership.user_id,
    )
    db.add(movement)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise MovementApiError(409, "Movement could not be recorded because it conflicts with existing data.")
    db.refresh(movement)
    return _view(db.execute(_movement_query().where(
        StockMovement.id == movement.id,
        StockMovement.company_id == membership.company_id,
    )).one())


def list_movements(db: Session, membership: CompanyMembership, *,
                   branch_id: UUID | None, ingredient_product_id: UUID | None,
                   movement_type: str | None, start_date: date | None,
                   end_date: date | None, batch_number: str | None,
                   state: str, limit: int, offset: int) -> dict:
    filters = [StockMovement.company_id == membership.company_id]
    if branch_id is not None:
        _authorize_branch(db, membership, branch_id)
        filters.append(StockMovement.branch_id == branch_id)
    elif membership.role in {"MANAGER", "STAFF"}:
        assigned = select(BranchMembership.branch_id).where(
            BranchMembership.company_membership_id == membership.id,
            BranchMembership.branch_id.in_(select(Branch.id).where(
                Branch.company_id == membership.company_id,
                Branch.is_active.is_(True))))
        filters.append(StockMovement.branch_id.in_(assigned))
    if ingredient_product_id is not None:
        filters.append(StockMovement.ingredient_product_id == ingredient_product_id)
    if movement_type is not None:
        filters.append(StockMovement.movement_type == movement_type)
    if start_date is not None:
        filters.append(StockMovement.movement_date >= start_date)
    if end_date is not None:
        filters.append(StockMovement.movement_date <= end_date)
    if batch_number is not None:
        filters.append(StockMovement.batch_number == batch_number)
    if state == "ACTIVE":
        filters.append(StockMovement.voided_at.is_(None))
    elif state == "VOIDED":
        filters.append(StockMovement.voided_at.is_not(None))

    total = db.scalar(select(func.count()).select_from(StockMovement).where(*filters)) or 0
    rows = db.execute(_movement_query().where(*filters).order_by(
        StockMovement.movement_date.desc(), StockMovement.created_at.desc(),
        StockMovement.id).limit(limit).offset(offset)).all()
    return {"items": [_view(row) for row in rows], "total": total,
        "limit": limit, "offset": offset}


def get_movement(db: Session, membership: CompanyMembership, movement_id: UUID) -> dict:
    row = db.execute(_movement_query().where(
        StockMovement.id == movement_id,
        StockMovement.company_id == membership.company_id,
    )).one_or_none()
    if row is None:
        raise MovementApiError(404, "Stock movement not found.")
    movement = row[0]
    _authorize_branch(db, membership, movement.branch_id)
    return _view(row)


def void_movement(db: Session, membership: CompanyMembership,
                  movement_id: UUID, reason: str) -> dict:
    if membership.role not in {"OWNER", "MANAGER"}:
        raise MovementApiError(403, "You do not have permission to void this stock movement.")
    movement = db.scalar(select(StockMovement).where(
        StockMovement.id == movement_id,
        StockMovement.company_id == membership.company_id,
    ).with_for_update())
    if movement is None:
        raise MovementApiError(404, "Stock movement not found.")
    _authorize_branch(db, membership, movement.branch_id)
    if movement.origin_type != "MANUAL":
        raise MovementApiError(409, "Upload-origin movements cannot be voided manually.")
    if movement.purchase_line_id is not None or movement.transfer_id is not None:
        raise MovementApiError(409, "Linked purchase and transfer movements cannot be voided manually.")
    if movement.voided_at is not None:
        raise MovementApiError(409, "Stock movement is already voided.")

    movement.voided_by_user_id = membership.user_id
    movement.voided_at = datetime.now(timezone.utc)
    movement.void_reason = reason
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise MovementApiError(409, "Movement could not be voided because it conflicts with existing data.")
    return get_movement(db, membership, movement.id)
