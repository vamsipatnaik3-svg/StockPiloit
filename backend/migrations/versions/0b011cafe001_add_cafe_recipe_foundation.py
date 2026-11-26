"""add product kinds and versioned recipe foundation

Revision ID: 0b011cafe001
Revises: 6c010a4fb32e
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0b011cafe001"
down_revision: Union[str, Sequence[str], None] = "6c010a4fb32e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A server default makes every existing catalogue row LEGACY without
    # guessing whether it is a sellable item or an ingredient.
    op.add_column(
        "products",
        sa.Column("product_kind", sa.String(length=20), server_default="LEGACY", nullable=False),
    )
    op.create_check_constraint(
        "ck_product_kind", "products",
        "product_kind IN ('MENU_ITEM', 'INGREDIENT', 'LEGACY')",
    )

    op.create_table(
        "recipe_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("menu_product_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_recipe_version_positive"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["menu_product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "menu_product_id", "version", name="uq_recipe_version_product_version"),
        sa.UniqueConstraint("company_id", "menu_product_id", "effective_from", name="uq_recipe_version_product_effective_date"),
    )
    op.create_index("ix_recipe_versions_company_id", "recipe_versions", ["company_id"])
    op.create_index("ix_recipe_versions_menu_product_id", "recipe_versions", ["menu_product_id"])
    op.create_index("ix_recipe_versions_effective_from", "recipe_versions", ["effective_from"])

    op.create_table(
        "recipe_ingredients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recipe_version_id", sa.Uuid(), nullable=False),
        sa.Column("ingredient_product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_recipe_ingredient_quantity_positive"),
        sa.ForeignKeyConstraint(["recipe_version_id"], ["recipe_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ingredient_product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recipe_ingredients_recipe_version_id", "recipe_ingredients", ["recipe_version_id"])
    op.create_index("ix_recipe_ingredients_ingredient_product_id", "recipe_ingredients", ["ingredient_product_id"])

    op.create_table(
        "modifier_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("menu_product_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("selection_min", sa.Integer(), server_default="0", nullable=False),
        sa.Column("selection_max", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("selection_min >= 0 AND selection_max >= selection_min", name="ck_modifier_group_selection_range"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["menu_product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("menu_product_id", "name", name="uq_modifier_group_menu_name"),
    )
    op.create_index("ix_modifier_groups_company_id", "modifier_groups", ["company_id"])
    op.create_index("ix_modifier_groups_menu_product_id", "modifier_groups", ["menu_product_id"])

    op.create_table(
        "modifier_options",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("modifier_group_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.ForeignKeyConstraint(["modifier_group_id"], ["modifier_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("modifier_group_id", "name", name="uq_modifier_option_group_name"),
    )
    op.create_index("ix_modifier_options_modifier_group_id", "modifier_options", ["modifier_group_id"])

    op.create_table(
        "modifier_recipe_ingredients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recipe_version_id", sa.Uuid(), nullable=False),
        sa.Column("modifier_option_id", sa.Uuid(), nullable=False),
        sa.Column("ingredient_product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_modifier_recipe_ingredient_quantity_positive"),
        sa.ForeignKeyConstraint(["recipe_version_id"], ["recipe_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["modifier_option_id"], ["modifier_options.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ingredient_product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_modifier_recipe_ingredients_recipe_version_id", "modifier_recipe_ingredients", ["recipe_version_id"])
    op.create_index("ix_modifier_recipe_ingredients_modifier_option_id", "modifier_recipe_ingredients", ["modifier_option_id"])
    op.create_index("ix_modifier_recipe_ingredients_ingredient_product_id", "modifier_recipe_ingredients", ["ingredient_product_id"])

    # Null preserves existing sales. New upload processing will pin the recipe
    # version selected for that sale date before calculating theoretical use.
    op.add_column("sales_records", sa.Column("recipe_version_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_sales_records_recipe_version_id_recipe_versions",
        "sales_records", "recipe_versions", ["recipe_version_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index("ix_sales_records_recipe_version_id", "sales_records", ["recipe_version_id"])

    op.create_table(
        "sales_record_modifiers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sales_record_id", sa.Uuid(), nullable=False),
        sa.Column("modifier_option_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["sales_record_id"], ["sales_records.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["modifier_option_id"], ["modifier_options.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sales_record_id", "modifier_option_id", name="uq_sales_record_modifier_option"),
    )
    op.create_index("ix_sales_record_modifiers_sales_record_id", "sales_record_modifiers", ["sales_record_id"])
    op.create_index("ix_sales_record_modifiers_modifier_option_id", "sales_record_modifiers", ["modifier_option_id"])


def downgrade() -> None:
    op.drop_index("ix_sales_record_modifiers_modifier_option_id", table_name="sales_record_modifiers")
    op.drop_index("ix_sales_record_modifiers_sales_record_id", table_name="sales_record_modifiers")
    op.drop_table("sales_record_modifiers")
    op.drop_index("ix_sales_records_recipe_version_id", table_name="sales_records")
    op.drop_constraint("fk_sales_records_recipe_version_id_recipe_versions", "sales_records", type_="foreignkey")
    op.drop_column("sales_records", "recipe_version_id")
    for name in ("ix_modifier_recipe_ingredients_ingredient_product_id",
                 "ix_modifier_recipe_ingredients_modifier_option_id",
                 "ix_modifier_recipe_ingredients_recipe_version_id"):
        op.drop_index(name, table_name="modifier_recipe_ingredients")
    op.drop_table("modifier_recipe_ingredients")
    op.drop_index("ix_modifier_options_modifier_group_id", table_name="modifier_options")
    op.drop_table("modifier_options")
    for name in ("ix_modifier_groups_menu_product_id", "ix_modifier_groups_company_id"):
        op.drop_index(name, table_name="modifier_groups")
    op.drop_table("modifier_groups")
    op.drop_index("ix_recipe_ingredients_ingredient_product_id", table_name="recipe_ingredients")
    op.drop_index("ix_recipe_ingredients_recipe_version_id", table_name="recipe_ingredients")
    op.drop_table("recipe_ingredients")
    for name in ("ix_recipe_versions_effective_from", "ix_recipe_versions_menu_product_id", "ix_recipe_versions_company_id"):
        op.drop_index(name, table_name="recipe_versions")
    op.drop_table("recipe_versions")
    op.drop_constraint("ck_product_kind", "products", type_="check")
    op.drop_column("products", "product_kind")
