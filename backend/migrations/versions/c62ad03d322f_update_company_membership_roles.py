
"""Update company membership roles.

Revision ID: c62ad03d322f
Revises: 5a1d2c9e8b43
"""

from typing import Sequence, Union

from alembic import op


# Revision identifiers.
revision: str = "c62ad03d322f"
down_revision: Union[str, Sequence[str], None] = "5a1d2c9e8b43"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove the existing role constraint.
    op.drop_constraint(
        "ck_company_membership_role",
        "company_memberships",
        type_="check",
    )

    # Migrate existing role values.
    op.execute(
        """
        UPDATE company_memberships
        SET role = 'MANAGER'
        WHERE role = 'ADMIN'
        """
    )

    op.execute(
        """
        UPDATE company_memberships
        SET role = 'ANALYST'
        WHERE role = 'VIEWER'
        """
    )

    # Add the new role constraint.
    op.create_check_constraint(
        "ck_company_membership_role",
        "company_memberships",
        "role IN ('OWNER', 'MANAGER', 'STAFF', 'ANALYST')",
    )


def downgrade() -> None:
    # Remove the new role constraint.
    op.drop_constraint(
        "ck_company_membership_role",
        "company_memberships",
        type_="check",
    )

    # Convert new-only roles to a role supported by the old schema.
    op.execute(
        """
        UPDATE company_memberships
        SET role = 'VIEWER'
        WHERE role IN ('STAFF', 'ANALYST')
        """
    )

    # Restore the old role constraint.
    op.create_check_constraint(
        "ck_company_membership_role",
        "company_memberships",
        "role IN ('OWNER', 'ADMIN', 'MANAGER', 'VIEWER')",
    )
