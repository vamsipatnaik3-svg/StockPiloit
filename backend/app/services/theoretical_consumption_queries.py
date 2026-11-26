from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.branch_scope import BranchAccessScope
from app.models import (Branch, DailyUpload, ModifierGroup, ModifierOption,
    ModifierRecipeIngredient, Product, RecipeIngredient, RecipeVersion,
    SalesRecord, SalesRecordModifier)
from app.services.theoretical_consumption import (IngredientLine,
    ModifierGroupRef, ModifierOptionRef, ModifierSelection, ProductRef,
    RecipeRef, SaleInput, ScopeInput, UploadRef)


def _product_ref(product: Product | None) -> ProductRef | None:
    if product is None:
        return None
    return ProductRef(product.id, product.company_id, product.sku,
        product.product_name, product.product_kind, product.unit_of_measure,
        product.is_active)


def load_theoretical_inputs(db: Session, company_id: UUID, start_date: date,
        end_date: date, scope: BranchAccessScope) -> tuple[tuple[ScopeInput, ...], tuple[SaleInput, ...]]:
    """Load only the tenant's current completed upload scopes and their sales facts."""
    if scope.company_id != company_id or (
            not scope.branch_ids and not (scope.role == "OWNER" and scope.scope_type == "COMPANY")):
        raise ValueError("Theoretical consumption requires a matching authorized branch scope.")
    upload_filters = [DailyUpload.company_id == company_id,
        DailyUpload.business_date >= start_date, DailyUpload.business_date <= end_date,
        Branch.company_id == company_id,
        DailyUpload.branch_id == Branch.id,
        *scope.criteria(DailyUpload.company_id, DailyUpload.branch_id)]
    uploads = db.execute(select(DailyUpload, Branch).join(
        Branch, Branch.id == DailyUpload.branch_id,
    ).where(*upload_filters).order_by(DailyUpload.business_date, Branch.name,
        DailyUpload.version)).all()

    scopes_by_key: dict[tuple[UUID, date], dict] = {}
    current_upload_ids: set[UUID] = set()
    for upload, branch in uploads:
        key = (branch.id, upload.business_date)
        bucket = scopes_by_key.setdefault(key, {
            "branch": branch, "date": upload.business_date, "usable": [], "any_upload": False,
        })
        bucket["any_upload"] = True
        if upload.is_current and upload.processing_status == "COMPLETED":
            bucket["usable"].append(upload)
            current_upload_ids.add(upload.id)

    scopes = tuple(ScopeInput(
        company_id=company_id,
        branch_id=bucket["branch"].id,
        branch_name=bucket["branch"].name,
        business_date=bucket["date"],
        uploads=tuple(UploadRef(item.id, item.version) for item in bucket["usable"]),
        unavailable_reason=None if bucket["usable"] else "NO_COMPLETED_CURRENT_UPLOAD",
    ) for bucket in scopes_by_key.values())

    if not current_upload_ids:
        return scopes, ()

    sales_rows = db.execute(select(SalesRecord, Product, DailyUpload, Branch)
        .join(DailyUpload, DailyUpload.id == SalesRecord.source_upload_id)
        .join(Branch, Branch.id == SalesRecord.branch_id)
        .outerjoin(Product, Product.id == SalesRecord.product_id)
        .where(
            SalesRecord.company_id == company_id,
            SalesRecord.source_upload_id.in_(current_upload_ids),
            SalesRecord.business_date >= start_date,
            SalesRecord.business_date <= end_date,
            DailyUpload.company_id == company_id,
            DailyUpload.branch_id == SalesRecord.branch_id,
            DailyUpload.business_date == SalesRecord.business_date,
            DailyUpload.is_current.is_(True),
            DailyUpload.processing_status == "COMPLETED",
            Branch.company_id == company_id,
        ).order_by(SalesRecord.business_date, Branch.name, SalesRecord.id)).all()
    if not sales_rows:
        return scopes, ()

    sales = [row[0] for row in sales_rows]
    sale_ids = [row.id for row in sales]
    menu_product_ids = {row.product_id for row in sales}
    recipe_ids = {row.recipe_version_id for row in sales if row.recipe_version_id is not None}
    recipe_rows = db.scalars(select(RecipeVersion).where(
        RecipeVersion.company_id == company_id,
        RecipeVersion.id.in_(recipe_ids))).all() if recipe_ids else []
    recipe_by_id = {item.id: item for item in recipe_rows}
    valid_recipe_ids = set(recipe_by_id)
    base_rows = db.scalars(select(RecipeIngredient).where(
        RecipeIngredient.recipe_version_id.in_(valid_recipe_ids))).all() if valid_recipe_ids else []
    modifier_rows = db.scalars(select(ModifierRecipeIngredient).where(
        ModifierRecipeIngredient.recipe_version_id.in_(valid_recipe_ids))).all() if valid_recipe_ids else []
    selection_rows = db.scalars(select(SalesRecordModifier).where(
        SalesRecordModifier.sales_record_id.in_(sale_ids))).all()

    option_ids = {item.modifier_option_id for item in selection_rows}
    option_ids.update(item.modifier_option_id for item in modifier_rows)
    options = db.scalars(select(ModifierOption).join(
        ModifierGroup, ModifierGroup.id == ModifierOption.modifier_group_id,
    ).where(ModifierGroup.company_id == company_id,
        ModifierOption.id.in_(option_ids))).all() if option_ids else []
    option_by_id = {item.id: item for item in options}
    group_ids = {item.modifier_group_id for item in options}
    groups_for_sales = db.scalars(select(ModifierGroup).where(
        ModifierGroup.company_id == company_id,
        ModifierGroup.menu_product_id.in_(menu_product_ids))).all() if menu_product_ids else []
    group_ids.update(item.id for item in groups_for_sales)
    groups = db.scalars(select(ModifierGroup).where(
        ModifierGroup.company_id == company_id,
        ModifierGroup.id.in_(group_ids))).all() if group_ids else []
    group_by_id = {item.id: item for item in groups}

    line_product_ids = {item.ingredient_product_id for item in (*base_rows, *modifier_rows)}
    line_product_ids.update(row.product_id for row in sales)
    products = db.scalars(select(Product).where(
        Product.company_id == company_id,
        Product.id.in_(line_product_ids))).all() if line_product_ids else []
    product_by_id = {item.id: item for item in products}

    def recipe_lines(lines) -> tuple[IngredientLine, ...]:
        return tuple(IngredientLine(_product_ref(product_by_id.get(item.ingredient_product_id)),
            item.quantity, item.unit) for item in lines)

    base_by_recipe: dict[UUID, list[RecipeIngredient]] = {}
    for item in base_rows:
        base_by_recipe.setdefault(item.recipe_version_id, []).append(item)
    modifiers_by_key: dict[tuple[UUID, UUID], list[ModifierRecipeIngredient]] = {}
    for item in modifier_rows:
        modifiers_by_key.setdefault((item.recipe_version_id, item.modifier_option_id), []).append(item)
    selections_by_sale: dict[UUID, list[SalesRecordModifier]] = {}
    for item in selection_rows:
        selections_by_sale.setdefault(item.sales_record_id, []).append(item)
    groups_by_menu: dict[UUID, list[ModifierGroup]] = {}
    for item in groups_for_sales:
        groups_by_menu.setdefault(item.menu_product_id, []).append(item)

    inputs: list[SaleInput] = []
    for record, menu_product, upload, branch in sales_rows:
        recipe_model = recipe_by_id.get(record.recipe_version_id) if record.recipe_version_id else None
        recipe_ref = None if recipe_model is None else RecipeRef(
            recipe_model.id, recipe_model.company_id, recipe_model.menu_product_id,
            recipe_model.effective_from, recipe_lines(base_by_recipe.get(recipe_model.id, [])))
        groups_ref = tuple(ModifierGroupRef(item.id, item.company_id,
            item.menu_product_id, item.name, item.selection_min, item.selection_max)
            for item in groups_by_menu.get(record.product_id, []))
        selections: list[ModifierSelection] = []
        for selection in selections_by_sale.get(record.id, []):
            option_model = option_by_id.get(selection.modifier_option_id)
            group_model = group_by_id.get(option_model.modifier_group_id) if option_model else None
            option_ref = None if option_model is None or group_model is None else ModifierOptionRef(
                option_model.id, group_model.id, group_model.company_id, group_model.menu_product_id)
            lines = modifiers_by_key.get((record.recipe_version_id, selection.modifier_option_id), []) if record.recipe_version_id else []
            selections.append(ModifierSelection(option_ref, selection.selection_quantity,
                recipe_lines(lines)))
        inputs.append(SaleInput(
            id=record.id, company_id=record.company_id, branch_id=record.branch_id,
            branch_name=branch.name, business_date=record.business_date,
            product=_product_ref(menu_product), quantity=record.quantity,
            recipe_version_id=record.recipe_version_id, recipe=recipe_ref,
            modifier_groups=groups_ref, modifiers=tuple(selections),
            source_upload=UploadRef(upload.id, upload.version),
        ))
    return scopes, tuple(inputs)
