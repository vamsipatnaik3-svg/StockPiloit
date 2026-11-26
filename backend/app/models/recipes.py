import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, ForeignKey,
    Integer, Numeric, String, UniqueConstraint, Uuid, func)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RecipeVersion(Base):
    """An immutable, company-wide recipe version for a menu Product."""

    __tablename__ = "recipe_versions"
    __table_args__ = (
        UniqueConstraint("company_id", "menu_product_id", "version", name="uq_recipe_version_product_version"),
        UniqueConstraint("company_id", "menu_product_id", "effective_from", name="uq_recipe_version_product_effective_date"),
        CheckConstraint("version > 0", name="ck_recipe_version_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    menu_product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_recipe_ingredient_quantity_positive"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_version_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("recipe_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    ingredient_product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)


class ModifierGroup(Base):
    __tablename__ = "modifier_groups"
    __table_args__ = (
        UniqueConstraint("menu_product_id", "name", name="uq_modifier_group_menu_name"),
        CheckConstraint("selection_min >= 0 AND selection_max >= selection_min", name="ck_modifier_group_selection_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    menu_product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    selection_min: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    selection_max: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class ModifierOption(Base):
    __tablename__ = "modifier_options"
    __table_args__ = (UniqueConstraint("modifier_group_id", "name", name="uq_modifier_option_group_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    modifier_group_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("modifier_groups.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class ModifierRecipeIngredient(Base):
    __tablename__ = "modifier_recipe_ingredients"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_modifier_recipe_ingredient_quantity_positive"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_version_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("recipe_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    modifier_option_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("modifier_options.id", ondelete="CASCADE"), nullable=False, index=True)
    ingredient_product_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)


class SalesRecordModifier(Base):
    """Modifier option selections, with count for aggregated sale rows."""

    __tablename__ = "sales_record_modifiers"
    __table_args__ = (
        UniqueConstraint("sales_record_id", "modifier_option_id", name="uq_sales_record_modifier_option"),
        CheckConstraint("selection_quantity IS NULL OR selection_quantity > 0", name="ck_sales_record_modifier_selection_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sales_record_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sales_records.id", ondelete="CASCADE"), nullable=False, index=True)
    modifier_option_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("modifier_options.id", ondelete="RESTRICT"), nullable=False, index=True)
    selection_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
