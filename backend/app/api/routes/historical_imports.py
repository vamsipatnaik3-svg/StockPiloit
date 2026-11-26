from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.api.routes.uploads import _authorized_upload
from app.db.session import SessionLocal, get_db
from app.models import (CompanyMembership, DailyUpload, HistoricalImportItem,
    HistoricalImportJob)
from app.services.storage import get_workbook_storage
from app.services.upload_processing import process_upload

router = APIRouter(tags=["Historical Imports"])


class HistoricalImportCreate(BaseModel):
    upload_ids: list[UUID] = Field(min_length=1, max_length=100)


def _job_summary(job: HistoricalImportJob):
    return {"id": str(job.id), "status": job.status, "total_files": job.total_files,
        "completed_files": job.completed_files, "failed_files": job.failed_files,
        "skipped_files": job.skipped_files,
        "progress_percent": round((job.completed_files + job.failed_files + job.skipped_files) * 100 / job.total_files) if job.total_files else 100,
        "date_start": job.date_start.isoformat() if job.date_start else None,
        "date_end": job.date_end.isoformat() if job.date_end else None,
        "branch_ids": [value for value in job.branch_ids.split(",") if value],
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None}


def _run_import_job(job_id: UUID) -> None:
    with SessionLocal() as db:
        job = db.get(HistoricalImportJob, job_id)
        if job is None:
            return
        job.status = "PROCESSING"
        job.started_at = datetime.now(timezone.utc)
        db.commit()
        items = db.scalars(select(HistoricalImportItem).join(DailyUpload,
            DailyUpload.id == HistoricalImportItem.upload_id).where(
            HistoricalImportItem.job_id == job_id,
            HistoricalImportItem.status == "QUEUED").order_by(
            DailyUpload.business_date, DailyUpload.version)).all()
        for item in items:
            item.status = "PROCESSING"
            db.commit()
            try:
                upload = db.get(DailyUpload, item.upload_id)
                if upload is None:
                    raise ValueError("Stored workbook is unavailable.")
                from app.models import Branch
                branch = db.get(Branch, upload.branch_id)
                content = get_workbook_storage().read(upload.object_key)
                result = process_upload(db, upload, branch, content)
                item = db.get(HistoricalImportItem, item.id)
                job = db.get(HistoricalImportJob, job_id)
                if result.processing_status == "COMPLETED":
                    item.status = "COMPLETED"
                    item.error_message = None
                    job.completed_files += 1
                elif result.processing_status == "SKIPPED":
                    item.status = "SKIPPED"
                    item.error_message = "A newer successful version is current."
                    job.skipped_files += 1
                else:
                    item.status = "FAILED"
                    item.error_message = f"Workbook validation reported {result.error_count} errors."
                    job.failed_files += 1
                item.completed_at = datetime.now(timezone.utc)
                db.commit()
            except Exception:
                db.rollback()
                item = db.get(HistoricalImportItem, item.id)
                job = db.get(HistoricalImportJob, job_id)
                item.status = "FAILED"
                item.error_message = "Processing failed. Review the workbook and retry the failed file."
                item.completed_at = datetime.now(timezone.utc)
                job.failed_files += 1
                db.commit()
        job = db.get(HistoricalImportJob, job_id)
        job.status = "PARTIAL_FAILED" if job.failed_files else "COMPLETED"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()


@router.post("", status_code=202)
def create_historical_import(data: HistoricalImportCreate, tasks: BackgroundTasks,
        actor: CompanyMembership = Depends(require_roles("OWNER", "MANAGER")), db: Session = Depends(get_db)):
    if len(set(data.upload_ids)) != len(data.upload_ids):
        raise HTTPException(status_code=422, detail="Each upload can appear only once in an import job.")
    uploads = []
    for upload_id in data.upload_ids:
        upload, _ = _authorized_upload(db, actor, upload_id)
        uploads.append(upload)
    dates = [upload.business_date for upload in uploads]
    branches = sorted({str(upload.branch_id) for upload in uploads})
    job = HistoricalImportJob(company_id=actor.company_id,
        initiated_by_membership_id=actor.id, status="QUEUED", total_files=len(uploads),
        date_start=min(dates), date_end=max(dates), branch_ids=",".join(branches))
    db.add(job)
    db.flush()
    for upload in uploads:
        already_processed = upload.processing_status in {"COMPLETED", "SKIPPED"}
        db.add(HistoricalImportItem(job_id=job.id, upload_id=upload.id,
            status="SKIPPED" if already_processed else "QUEUED",
            error_message="Upload was already processed; no new records were written." if already_processed else None))
        if already_processed:
            job.skipped_files += 1
    if job.skipped_files == job.total_files:
        job.status = "COMPLETED"
        job.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    if job.skipped_files < job.total_files:
        tasks.add_task(_run_import_job, job.id)
    return _job_summary(job)


def _get_job(db: Session, actor: CompanyMembership, job_id: UUID):
    job = db.scalar(select(HistoricalImportJob).where(
        HistoricalImportJob.id == job_id, HistoricalImportJob.company_id == actor.company_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Historical import not found.")
    items = db.scalars(select(HistoricalImportItem).where(HistoricalImportItem.job_id == job.id)).all()
    result_items = []
    for item in items:
        upload, _ = _authorized_upload(db, actor, item.upload_id)
        result_items.append({"upload_id": str(upload.id), "filename": upload.original_filename,
            "branch_id": str(upload.branch_id), "business_date": upload.business_date.isoformat(),
            "status": item.status, "error_message": item.error_message})
    return job, result_items


@router.get("")
def list_historical_imports(actor: CompanyMembership = Depends(require_roles("OWNER", "MANAGER")), db: Session = Depends(get_db)):
    jobs = db.scalars(select(HistoricalImportJob).where(
        HistoricalImportJob.company_id == actor.company_id).order_by(HistoricalImportJob.created_at.desc())).all()
    visible = []
    for job in jobs:
        items = db.scalars(select(HistoricalImportItem).where(HistoricalImportItem.job_id == job.id)).all()
        try:
            for item in items:
                _authorized_upload(db, actor, item.upload_id)
            visible.append(_job_summary(job))
        except HTTPException:
            continue
    return visible


@router.get("/{job_id}")
def get_historical_import(job_id: UUID, actor: CompanyMembership = Depends(require_roles("OWNER", "MANAGER")), db: Session = Depends(get_db)):
    job, items = _get_job(db, actor, job_id)
    return {**_job_summary(job), "files": items}


@router.post("/{job_id}/retry", status_code=202)
def retry_historical_import(job_id: UUID, tasks: BackgroundTasks,
        actor: CompanyMembership = Depends(require_roles("OWNER", "MANAGER")), db: Session = Depends(get_db)):
    job, _ = _get_job(db, actor, job_id)
    if job.status not in {"PARTIAL_FAILED", "FAILED"} or not job.failed_files:
        raise HTTPException(status_code=409, detail="This job has no failed files to retry.")
    failed = db.scalars(select(HistoricalImportItem).where(
        HistoricalImportItem.job_id == job.id, HistoricalImportItem.status == "FAILED")).all()
    for item in failed:
        item.status = "QUEUED"
        item.error_message = None
        item.completed_at = None
    job.failed_files = 0
    job.status = "QUEUED"
    job.completed_at = None
    db.commit()
    tasks.add_task(_run_import_job, job.id)
    return _job_summary(job)
