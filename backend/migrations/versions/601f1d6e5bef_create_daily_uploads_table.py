
"""create daily uploads table

Revision ID: 601f1d6e5bef
Revises: 834e16da7e06
Create Date: 2026-11-25

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "601f1d6e5bef"
down_revision: Union[str, Sequence[str], None] = "834e16da7e06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_uploads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("uploaded_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="INITIATED",
            nullable=False,
        ),
        sa.Column(
            "is_current",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('INITIATED', 'UPLOADED', 'FAILED')",
            name="ck_daily_upload_status",
        ),
        sa.CheckConstraint(
            "file_size_bytes IS NULL OR file_size_bytes > 0",
            name="ck_daily_upload_file_size_positive",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_daily_upload_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"],
            ["branches.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_membership_id"],
            ["company_memberships.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "branch_id",
            "business_date",
            "version",
            name="uq_daily_upload_branch_date_version",
        ),
        sa.UniqueConstraint("object_key"),
    )

    op.create_index(
        op.f("ix_daily_uploads_branch_id"),
        "daily_uploads",
        ["branch_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_daily_uploads_business_date"),
        "daily_uploads",
        ["business_date"],
        unique=False,
    )

    op.create_index(
        op.f("ix_daily_uploads_company_id"),
        "daily_uploads",
        ["company_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_daily_uploads_uploaded_by_membership_id"),
        "daily_uploads",
        ["uploaded_by_membership_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_daily_uploads_uploaded_by_membership_id"),
        table_name="daily_uploads",
    )

    op.drop_index(
        op.f("ix_daily_uploads_company_id"),
        table_name="daily_uploads",
    )

    op.drop_index(
        op.f("ix_daily_uploads_business_date"),
        table_name="daily_uploads",
    )

    op.drop_index(
        op.f("ix_daily_uploads_branch_id"),
        table_name="daily_uploads",
    )

    op.drop_table("daily_uploads")
