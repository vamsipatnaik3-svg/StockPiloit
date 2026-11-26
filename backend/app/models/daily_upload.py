
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DailyUpload(Base):
    __tablename__ = "daily_uploads"

    __table_args__ = (
        UniqueConstraint(
            "branch_id",
            "business_date",
            "version",
            name="uq_daily_upload_branch_date_version",
        ),
        UniqueConstraint(
            "company_id", "branch_id", "id",
            name="uq_daily_upload_company_branch_id",
        ),
        UniqueConstraint(
            "company_id", "branch_id", "id", "business_date",
            name="uq_daily_upload_company_branch_id_date",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_daily_upload_version_positive",
        ),
        CheckConstraint(
            "status IN ('INITIATED', 'UPLOADED', 'FAILED')",
            name="ck_daily_upload_status",
        ),
        CheckConstraint(
            "file_size_bytes IS NULL OR file_size_bytes > 0",
            name="ck_daily_upload_file_size_positive",
        ),
        Index(
            "uq_daily_upload_current_branch_date",
            "branch_id",
            "business_date",
            unique=True,
            sqlite_where=text("is_current = 1"),
            postgresql_where=text("is_current = true"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    branch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    business_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )

    uploaded_by_membership_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("company_memberships.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    object_key: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        unique=True,
    )

    original_filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    content_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    file_size_bytes: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="INITIATED",
        server_default="INITIATED",
    )

    is_current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    processing_status: Mapped[str] = mapped_column(String(30), nullable=False, default="QUEUED", server_default="QUEUED")
    processing_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    rows_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rows_accepted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rows_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
