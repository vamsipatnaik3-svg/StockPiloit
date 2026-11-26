from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.db.session import get_db
from app.models import CompanyMembership
from app.schemas.staff_operations import (ConfirmableReceiptListResponse,
    ReceiptConfirmationCreate, ReceiptConfirmationListResponse,
    ReceiptConfirmationResponse, StockCountCreate, StockCountListResponse,
    StockCountResponse, WasteDamageCreate)
from app.schemas.stock_movement import StockMovementListResponse, StockMovementResponse
from app.services.staff_operations import (confirm_purchase_receipt,
    create_stock_count, get_receipt_confirmation, get_stock_count,
    get_waste_damage, list_confirmable_receipts, list_receipt_confirmations,
    list_stock_counts, list_waste_damage, record_waste_damage)


router = APIRouter(tags=["Staff Operations"])
OPERATIONAL_ROLES = ("OWNER", "MANAGER", "STAFF")
COUNT_ROLES = ("OWNER", "STAFF")
RECEIPT_ROLES = ("OWNER", "STAFF")


def _validate_time_range(start_at: datetime | None, end_at: datetime | None) -> None:
    for value in (start_at, end_at):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise HTTPException(status_code=422,
                detail="Timestamp filters must include a timezone offset.")
    if start_at is not None and end_at is not None and start_at > end_at:
        raise HTTPException(status_code=422,
            detail="start_at must be on or before end_at.")


@router.post("/stock-counts", response_model=StockCountResponse)
def submit_stock_count(data: StockCountCreate, response: Response,
        membership: CompanyMembership = Depends(require_roles(*COUNT_ROLES)),
        db: Session = Depends(get_db)):
    result, created = create_stock_count(db, membership, data)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return result


@router.get("/stock-counts", response_model=StockCountListResponse)
def get_stock_counts(branch_id: UUID | None = None,
        start_at: datetime | None = None, end_at: datetime | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        membership: CompanyMembership = Depends(require_roles(*COUNT_ROLES)),
        db: Session = Depends(get_db)):
    _validate_time_range(start_at, end_at)
    return list_stock_counts(db, membership, branch_id=branch_id,
        start_at=start_at, end_at=end_at, limit=limit, offset=offset)


@router.get("/stock-counts/{submission_id}", response_model=StockCountResponse)
def get_stock_count_detail(submission_id: UUID,
        membership: CompanyMembership = Depends(require_roles(*COUNT_ROLES)),
        db: Session = Depends(get_db)):
    return get_stock_count(db, membership, submission_id)


@router.post("/waste-events", response_model=StockMovementResponse)
def create_waste_damage_event(data: WasteDamageCreate, response: Response,
        membership: CompanyMembership = Depends(require_roles(*OPERATIONAL_ROLES)),
        db: Session = Depends(get_db)):
    result, created = record_waste_damage(db, membership, data)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return result


@router.get("/waste-events", response_model=StockMovementListResponse)
def get_waste_damage_events(branch_id: UUID | None = None,
        start_date: date | None = None, end_date: date | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        membership: CompanyMembership = Depends(require_roles(*OPERATIONAL_ROLES)),
        db: Session = Depends(get_db)):
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(status_code=422,
            detail="start_date must be on or before end_date.")
    return list_waste_damage(db, membership, branch_id=branch_id,
        start_date=start_date, end_date=end_date, limit=limit, offset=offset)


@router.get("/waste-events/{movement_id}", response_model=StockMovementResponse)
def get_waste_damage_detail(movement_id: UUID,
        membership: CompanyMembership = Depends(require_roles(*OPERATIONAL_ROLES)),
        db: Session = Depends(get_db)):
    return get_waste_damage(db, membership, movement_id)


@router.get("/receipts/confirmable", response_model=ConfirmableReceiptListResponse)
def get_confirmable_receipts(branch_id: UUID | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        membership: CompanyMembership = Depends(require_roles(*RECEIPT_ROLES)),
        db: Session = Depends(get_db)):
    return list_confirmable_receipts(db, membership, branch_id=branch_id,
        limit=limit, offset=offset)


@router.post("/receipts/{receipt_identity_id}/confirm",
        response_model=ReceiptConfirmationResponse)
def confirm_receipt(receipt_identity_id: UUID, data: ReceiptConfirmationCreate,
        response: Response,
        membership: CompanyMembership = Depends(require_roles(*RECEIPT_ROLES)),
        db: Session = Depends(get_db)):
    result, created = confirm_purchase_receipt(db, membership,
        receipt_identity_id, data.idempotency_key)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return result


@router.get("/receipt-confirmations", response_model=ReceiptConfirmationListResponse)
def get_receipt_confirmations(branch_id: UUID | None = None,
        start_at: datetime | None = None, end_at: datetime | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        membership: CompanyMembership = Depends(require_roles(*RECEIPT_ROLES)),
        db: Session = Depends(get_db)):
    _validate_time_range(start_at, end_at)
    return list_receipt_confirmations(db, membership, branch_id=branch_id,
        start_at=start_at, end_at=end_at, limit=limit, offset=offset)


@router.get("/receipt-confirmations/{confirmation_id}",
        response_model=ReceiptConfirmationResponse)
def get_receipt_confirmation_detail(confirmation_id: UUID,
        membership: CompanyMembership = Depends(require_roles(*RECEIPT_ROLES)),
        db: Session = Depends(get_db)):
    return get_receipt_confirmation(db, membership, confirmation_id)
