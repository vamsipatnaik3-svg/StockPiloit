from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.db.session import get_db
from app.models import CompanyMembership
from app.schemas.stock_movement import (ManualMovementCreate,
    ManualMovementVoid, StockMovementListResponse, StockMovementResponse)
from app.services.stock_movements import (MovementApiError, create_manual_movement,
    get_movement, list_movements, void_movement)


router = APIRouter(tags=["Stock Movements"])


def _raise_api_error(error: MovementApiError):
    raise HTTPException(status_code=error.status_code, detail=error.detail)


@router.post("", response_model=StockMovementResponse,
             status_code=status.HTTP_201_CREATED)
def create_stock_movement(
    data: ManualMovementCreate,
    membership: CompanyMembership = Depends(require_roles("OWNER", "MANAGER")),
    db: Session = Depends(get_db),
):
    try:
        return create_manual_movement(db, membership, data)
    except MovementApiError as error:
        _raise_api_error(error)


@router.get("", response_model=StockMovementListResponse)
def get_stock_movements(
    branch_id: UUID | None = None,
    ingredient_product_id: UUID | None = None,
    movement_type: Literal[
        "PURCHASE_RECEIPT", "OTHER_INFLOW", "POSITIVE_ADJUSTMENT", "TRANSFER_IN",
        "WASTE", "STAFF_CONSUMPTION", "DAMAGE", "NEGATIVE_ADJUSTMENT",
        "OTHER_OUTFLOW", "TRANSFER_OUT",
    ] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    batch_number: str | None = Query(default=None, max_length=120),
    state: Literal["ACTIVE", "VOIDED", "ALL"] = "ACTIVE",
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    membership: CompanyMembership = Depends(require_roles("OWNER", "MANAGER")),
    db: Session = Depends(get_db),
):
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date.")
    if batch_number is not None:
        batch_number = batch_number.strip()
        if not batch_number:
            raise HTTPException(status_code=422, detail="batch_number cannot be blank.")
    try:
        return list_movements(db, membership, branch_id=branch_id,
            ingredient_product_id=ingredient_product_id, movement_type=movement_type,
            start_date=start_date, end_date=end_date, batch_number=batch_number,
            state=state, limit=limit, offset=offset)
    except MovementApiError as error:
        _raise_api_error(error)


@router.get("/{movement_id}", response_model=StockMovementResponse)
def get_stock_movement(
    movement_id: UUID,
    membership: CompanyMembership = Depends(require_roles("OWNER", "MANAGER")),
    db: Session = Depends(get_db),
):
    try:
        return get_movement(db, membership, movement_id)
    except MovementApiError as error:
        _raise_api_error(error)


@router.post("/{movement_id}/void", response_model=StockMovementResponse)
def void_stock_movement(
    movement_id: UUID,
    data: ManualMovementVoid,
    membership: CompanyMembership = Depends(require_roles("OWNER", "MANAGER")),
    db: Session = Depends(get_db),
):
    try:
        return void_movement(db, membership, movement_id, data.reason)
    except MovementApiError as error:
        _raise_api_error(error)
