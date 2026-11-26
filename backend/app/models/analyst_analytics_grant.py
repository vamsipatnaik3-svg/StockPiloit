import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AnalystAnalyticsGrant(Base):
    """Auditable, explicit read-only analytics scope for one membership."""

    __tablename__ = "analyst_analytics_grants"
    __table_args__ = (
        CheckConstraint("scope_type IN ('COMPANY', 'BRANCHES')",
                        name="ck_analyst_grant_scope_type"),
        CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_membership_id IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_membership_id IS NOT NULL)",
            name="ck_analyst_grant_revocation_audit",
        ),
        UniqueConstraint("company_id", "id", name="uq_analyst_grant_company_id"),
        ForeignKeyConstraint(
            ["company_id", "analyst_membership_id"],
            ["company_memberships.company_id", "company_memberships.id"],
            ondelete="CASCADE", name="fk_analyst_grant_target_membership",
        ),
        ForeignKeyConstraint(
            ["company_id", "granted_by_membership_id"],
            ["company_memberships.company_id", "company_memberships.id"],
            ondelete="RESTRICT", name="fk_analyst_grant_creator_membership",
        ),
        ForeignKeyConstraint(
            ["company_id", "revoked_by_membership_id"],
            ["company_memberships.company_id", "company_memberships.id"],
            ondelete="RESTRICT", name="fk_analyst_grant_revoker_membership",
        ),
        Index("uq_analyst_grant_one_active", "company_id", "analyst_membership_id",
              unique=True, postgresql_where=text("revoked_at IS NULL"),
              sqlite_where=text("revoked_at IS NULL")),
        Index("ix_analyst_grants_company_created", "company_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True,
        default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    analyst_membership_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    granted_by_membership_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
        server_default=func.now(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)


class AnalystAnalyticsGrantBranch(Base):
    """Branch membership in a selected-branch analyst grant."""

    __tablename__ = "analyst_analytics_grant_branches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "grant_id"],
            ["analyst_analytics_grants.company_id", "analyst_analytics_grants.id"],
            ondelete="CASCADE", name="fk_analyst_grant_branch_grant_scope",
        ),
        ForeignKeyConstraint(
            ["company_id", "branch_id"], ["branches.company_id", "branches.id"],
            ondelete="RESTRICT", name="fk_analyst_grant_branch_company_scope",
        ),
        Index("ix_analyst_grant_branches_company_branch", "company_id", "branch_id"),
    )

    grant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
