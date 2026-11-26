"""add scoped, auditable analyst analytics grants

Revision ID: 9f010cafe005
Revises: 8e010cafe004
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9f010cafe005"
down_revision: Union[str, Sequence[str], None] = "8e010cafe004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Composite membership references enforce tenant consistency for both the
    # target analyst and the owner who grants/revokes access.
    op.create_unique_constraint(
        "uq_company_membership_company_id_id", "company_memberships",
        ["company_id", "id"],
    )
    op.create_table(
        "analyst_analytics_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("analyst_membership_id", sa.Uuid(), nullable=False),
        sa.Column("granted_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_membership_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("scope_type IN ('COMPANY', 'BRANCHES')",
                           name="ck_analyst_grant_scope_type"),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_membership_id IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by_membership_id IS NOT NULL)",
            name="ck_analyst_grant_revocation_audit",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "analyst_membership_id"],
            ["company_memberships.company_id", "company_memberships.id"],
            ondelete="CASCADE", name="fk_analyst_grant_target_membership",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "granted_by_membership_id"],
            ["company_memberships.company_id", "company_memberships.id"],
            ondelete="RESTRICT", name="fk_analyst_grant_creator_membership",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "revoked_by_membership_id"],
            ["company_memberships.company_id", "company_memberships.id"],
            ondelete="RESTRICT", name="fk_analyst_grant_revoker_membership",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "id", name="uq_analyst_grant_company_id"),
    )
    op.create_index("uq_analyst_grant_one_active", "analyst_analytics_grants",
        ["company_id", "analyst_membership_id"], unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
        sqlite_where=sa.text("revoked_at IS NULL"))
    op.create_index("ix_analyst_grants_company_created", "analyst_analytics_grants",
        ["company_id", "created_at"], unique=False)
    op.create_table(
        "analyst_analytics_grant_branches",
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id", "grant_id"],
            ["analyst_analytics_grants.company_id", "analyst_analytics_grants.id"],
            ondelete="CASCADE", name="fk_analyst_grant_branch_grant_scope",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "branch_id"], ["branches.company_id", "branches.id"],
            ondelete="RESTRICT", name="fk_analyst_grant_branch_company_scope",
        ),
        sa.PrimaryKeyConstraint("grant_id", "branch_id"),
    )
    op.create_index("ix_analyst_grant_branches_company_branch",
        "analyst_analytics_grant_branches", ["company_id", "branch_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    has_grants = bind.execute(sa.text(
        "SELECT 1 FROM analyst_analytics_grants LIMIT 1"
    )).first()
    if has_grants is not None:
        raise RuntimeError(
            "Cannot downgrade Analyst analytics grants while grant audit records exist."
        )
    op.drop_index("ix_analyst_grant_branches_company_branch",
                  table_name="analyst_analytics_grant_branches")
    op.drop_table("analyst_analytics_grant_branches")
    op.drop_index("ix_analyst_grants_company_created",
                  table_name="analyst_analytics_grants")
    op.drop_index("uq_analyst_grant_one_active",
                  table_name="analyst_analytics_grants")
    op.drop_table("analyst_analytics_grants")
    op.drop_constraint("uq_company_membership_company_id_id",
                       "company_memberships", type_="unique")
