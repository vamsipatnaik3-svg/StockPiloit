from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.core.config import settings
from app.db.session import get_db
from app.models import Branch, BranchMembership, CompanyMembership, DailyUpload, UploadValidationIssue
from app.services.storage import get_workbook_storage
from app.services.upload_processing import process_upload

router = APIRouter(tags=["Uploads"])
XLSX_TYPES = {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/octet-stream"}
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _authorized_branch(db: Session, actor: CompanyMembership, branch_id: UUID) -> Branch:
    branch = db.scalar(select(Branch).where(Branch.id == branch_id, Branch.company_id == actor.company_id, Branch.is_active.is_(True)))
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found.")
    if actor.role == "MANAGER" and db.scalar(select(BranchMembership.id).where(
        BranchMembership.branch_id == branch.id,
        BranchMembership.company_membership_id == actor.id,
    )) is None:
        raise HTTPException(status_code=403, detail="You do not have access to this branch.")
    return branch


def _upload_view(upload: DailyUpload):
    return {
        "id": str(upload.id), "branch_id": str(upload.branch_id),
        "business_date": upload.business_date.isoformat(), "original_filename": upload.original_filename,
        "version": upload.version, "status": upload.status, "is_current": upload.is_current,
        "checksum_sha256": upload.checksum_sha256, "processing_status": upload.processing_status,
        "rows_read": upload.rows_read, "rows_accepted": upload.rows_accepted,
        "rows_rejected": upload.rows_rejected, "warning_count": upload.warning_count,
        "error_count": upload.error_count,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_workbook(
    branch_id: UUID = Form(), business_date: date = Form(),
    file: UploadFile = File(), actor: CompanyMembership = Depends(require_roles("OWNER", "MANAGER")),
    db: Session = Depends(get_db),
):
    branch = _authorized_branch(db, actor, branch_id)
    if Path(file.filename or "").suffix.lower() != ".xlsx" or file.content_type not in XLSX_TYPES:
        raise HTTPException(status_code=415, detail="Upload a valid .xlsx workbook.")
    content = await file.read(settings.max_upload_size_bytes + 1)
    if not content or len(content) > settings.max_upload_size_bytes:
        raise HTTPException(status_code=413, detail="Workbook must be between 1 byte and 20 MB.")
    checksum = sha256(content).hexdigest()
    duplicate = db.scalar(select(DailyUpload).where(DailyUpload.company_id == actor.company_id,
        DailyUpload.branch_id == branch.id, DailyUpload.business_date == business_date,
        DailyUpload.checksum_sha256 == checksum))
    if duplicate:
        raise HTTPException(status_code=409, detail={"code": "DUPLICATE_FILE", "upload_id": str(duplicate.id)})
    version = (db.scalar(select(DailyUpload.version).where(
        DailyUpload.branch_id == branch.id, DailyUpload.business_date == business_date
    ).order_by(DailyUpload.version.desc()).limit(1)) or 0) + 1
    upload_id = uuid4()
    storage = get_workbook_storage()
    object_key = storage.store(upload_id, content)
    upload = DailyUpload(id=upload_id, company_id=actor.company_id, branch_id=branch.id,
        business_date=business_date, uploaded_by_membership_id=actor.id,
        object_key=object_key, original_filename=Path(file.filename or "workbook.xlsx").name[:255],
        content_type=file.content_type or XLSX_MIME, file_size_bytes=len(content),
        version=version, status="UPLOADED", uploaded_at=datetime.now(timezone.utc),
        checksum_sha256=checksum, processing_status="QUEUED")
    db.add(upload)
    try:
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(object_key)
        raise
    db.refresh(upload)
    return _upload_view(upload)


@router.get("")
def list_uploads(actor: CompanyMembership = Depends(require_roles("OWNER", "MANAGER")), db: Session = Depends(get_db)):
    query = select(DailyUpload).where(DailyUpload.company_id == actor.company_id)
    if actor.role == "MANAGER":
        allowed = select(BranchMembership.branch_id).where(BranchMembership.company_membership_id == actor.id)
        query = query.where(DailyUpload.branch_id.in_(allowed))
    return [_upload_view(item) for item in db.scalars(query.order_by(DailyUpload.created_at.desc())).all()]


def _authorized_upload(db: Session, actor: CompanyMembership, upload_id: UUID) -> tuple[DailyUpload, Branch]:
    upload = db.scalar(select(DailyUpload).where(DailyUpload.id == upload_id, DailyUpload.company_id == actor.company_id))
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found.")
    return upload, _authorized_branch(db, actor, upload.branch_id)


@router.post("/{upload_id}/process")
def process_upload_endpoint(upload_id: UUID, actor: CompanyMembership = Depends(require_roles("OWNER", "MANAGER")), db: Session = Depends(get_db)):
    upload, branch = _authorized_upload(db, actor, upload_id)
    storage = get_workbook_storage()
    try:
        content = storage.read(upload.object_key)
    except FileNotFoundError:
        raise HTTPException(status_code=410, detail="The stored workbook is no longer available.")
    result = process_upload(db, upload, branch, content)
    return _upload_view(result)


@router.get("/{upload_id}/processing-status")
def processing_status(upload_id: UUID, actor: CompanyMembership = Depends(require_roles("OWNER", "MANAGER")), db: Session = Depends(get_db)):
    upload, _ = _authorized_upload(db, actor, upload_id)
    return _upload_view(upload)


@router.get("/{upload_id}/validation-report")
def validation_report(upload_id: UUID, actor: CompanyMembership = Depends(require_roles("OWNER", "MANAGER")), db: Session = Depends(get_db)):
    upload, _ = _authorized_upload(db, actor, upload_id)
    issues = db.scalars(select(UploadValidationIssue).where(UploadValidationIssue.upload_id == upload.id).order_by(UploadValidationIssue.id)).all()
    return {"upload_id": str(upload.id), "summary": _upload_view(upload), "issues": [
        {"severity": item.severity, "sheet": item.sheet, "row": item.row_number,
         "code": item.code, "message": item.message} for item in issues
    ]}
