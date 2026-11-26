from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (CompanyMembership, ModifierGroup, ModifierOption,
    ModifierRecipeIngredient, Product, RecipeIngredient, RecipeVersion)
from app.schemas.recipe import ModifierGroupCreate, ModifierOptionCreate, RecipeVersionCreate


class RecipeInputError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def _menu_product(db: Session, membership: CompanyMembership,
                  product_id: UUID, *, require_active: bool = False) -> Product:
    conditions = [Product.id == product_id, Product.company_id == membership.company_id,
        Product.product_kind == "MENU_ITEM"]
    if require_active:
        conditions.append(Product.is_active.is_(True))
    product = db.scalar(select(Product).where(*conditions))
    if product is None:
        raise RecipeInputError(404, "Menu item not found in this company.")
    return product


def _ingredient_products(db: Session, membership: CompanyMembership,
                         ingredient_ids: set[UUID]) -> dict[UUID, Product]:
    products = db.scalars(select(Product).where(
        Product.company_id == membership.company_id,
        Product.id.in_(ingredient_ids), Product.product_kind == "INGREDIENT",
        Product.is_active.is_(True),
    )).all() if ingredient_ids else []
    result = {product.id: product for product in products}
    if len(result) != len(ingredient_ids):
        raise RecipeInputError(422, "Every recipe ingredient must be an active INGREDIENT in this company.")
    return result


def list_recipe_menus(db: Session, membership: CompanyMembership) -> list[dict]:
    products = db.scalars(select(Product).where(
        Product.company_id == membership.company_id,
        Product.product_kind == "MENU_ITEM",
    ).order_by(Product.product_name)).all()
    versions = db.scalars(select(RecipeVersion).where(
        RecipeVersion.company_id == membership.company_id,
    ).order_by(RecipeVersion.effective_from.desc(), RecipeVersion.version.desc())).all()
    latest: dict[UUID, RecipeVersion] = {}
    for version in versions:
        latest.setdefault(version.menu_product_id, version)
    return [{
        "id": product.id,
        "sku": product.sku,
        "product_name": product.product_name,
        "unit_of_measure": product.unit_of_measure,
        "is_active": product.is_active,
        "latest_version": latest.get(product.id).version if product.id in latest else None,
        "latest_effective_from": latest.get(product.id).effective_from if product.id in latest else None,
    } for product in products]


def list_modifier_groups(db: Session, membership: CompanyMembership,
                         menu_product_id: UUID) -> list[dict]:
    _menu_product(db, membership, menu_product_id)
    groups = db.scalars(select(ModifierGroup).where(
        ModifierGroup.company_id == membership.company_id,
        ModifierGroup.menu_product_id == menu_product_id,
    ).order_by(ModifierGroup.name)).all()
    options = db.scalars(select(ModifierOption).join(
        ModifierGroup, ModifierGroup.id == ModifierOption.modifier_group_id,
    ).where(ModifierGroup.menu_product_id == menu_product_id,
        ModifierGroup.company_id == membership.company_id,
    ).order_by(ModifierOption.name)).all()
    options_by_group: dict[UUID, list[ModifierOption]] = {}
    for option in options:
        options_by_group.setdefault(option.modifier_group_id, []).append(option)
    return [{
        "id": group.id,
        "menu_product_id": group.menu_product_id,
        "name": group.name,
        "selection_min": group.selection_min,
        "selection_max": group.selection_max,
        "options": [{"id": option.id, "name": option.name, "is_active": option.is_active}
                    for option in options_by_group.get(group.id, [])],
    } for group in groups]


def recipe_version_view(db: Session, version: RecipeVersion) -> dict:
    base_rows = db.execute(select(RecipeIngredient, Product).join(
        Product, Product.id == RecipeIngredient.ingredient_product_id,
    ).where(RecipeIngredient.recipe_version_id == version.id).order_by(Product.product_name)).all()
    modifier_rows = db.execute(select(ModifierRecipeIngredient, ModifierOption,
        ModifierGroup, Product).join(ModifierOption,
        ModifierOption.id == ModifierRecipeIngredient.modifier_option_id).join(
        ModifierGroup, ModifierGroup.id == ModifierOption.modifier_group_id).join(
        Product, Product.id == ModifierRecipeIngredient.ingredient_product_id).where(
            ModifierRecipeIngredient.recipe_version_id == version.id,
            ModifierGroup.menu_product_id == version.menu_product_id,
        ).order_by(ModifierGroup.name, ModifierOption.name, Product.product_name)).all()
    return {
        "id": version.id,
        "menu_product_id": version.menu_product_id,
        "version": version.version,
        "effective_from": version.effective_from,
        "ingredients": [{
            "ingredient_product_id": line.ingredient_product_id,
            "ingredient_name": product.product_name,
            "sku": product.sku,
            "quantity": line.quantity,
            "unit": line.unit,
        } for line, product in base_rows],
        "modifier_ingredients": [{
            "modifier_option_id": option.id,
            "modifier_group": group.name,
            "modifier_option": option.name,
            "ingredient_product_id": line.ingredient_product_id,
            "ingredient_name": ingredient.product_name,
            "sku": ingredient.sku,
            "quantity": line.quantity,
            "unit": line.unit,
        } for line, option, group, ingredient in modifier_rows],
    }


def recipe_menu_detail(db: Session, membership: CompanyMembership,
                       menu_product_id: UUID) -> dict:
    product = _menu_product(db, membership, menu_product_id)
    versions = db.scalars(select(RecipeVersion).where(
        RecipeVersion.company_id == membership.company_id,
        RecipeVersion.menu_product_id == product.id,
    ).order_by(RecipeVersion.version.desc())).all()
    return {
        "menu_item": {"id": product.id, "sku": product.sku, "product_name": product.product_name,
                      "unit_of_measure": product.unit_of_measure, "is_active": product.is_active},
        "versions": [recipe_version_view(db, version) for version in versions],
        "modifier_groups": list_modifier_groups(db, membership, product.id),
    }


def resolve_recipe_version(db: Session, membership: CompanyMembership,
                           menu_product_id: UUID, business_date: date) -> RecipeVersion | None:
    product = _menu_product(db, membership, menu_product_id)
    return db.scalar(select(RecipeVersion).where(
        RecipeVersion.company_id == membership.company_id,
        RecipeVersion.menu_product_id == product.id,
        RecipeVersion.effective_from <= business_date,
    ).order_by(RecipeVersion.effective_from.desc()).limit(1))


def create_modifier_group(db: Session, membership: CompanyMembership,
                          menu_product_id: UUID, data: ModifierGroupCreate) -> dict:
    product = _menu_product(db, membership, menu_product_id, require_active=True)
    group = ModifierGroup(company_id=membership.company_id, menu_product_id=product.id,
        name=data.name.strip(), selection_min=data.selection_min, selection_max=data.selection_max)
    db.add(group)
    try:
        db.flush()
        db.add_all([ModifierOption(modifier_group_id=group.id, name=name.strip()) for name in data.options])
        db.commit()
    except IntegrityError:
        db.rollback()
        raise RecipeInputError(409, "A modifier group with this name already exists for the menu item.")
    return next(item for item in list_modifier_groups(db, membership, product.id) if item["id"] == group.id)


def add_modifier_option(db: Session, membership: CompanyMembership,
                        group_id: UUID, data: ModifierOptionCreate) -> dict:
    group = db.scalar(select(ModifierGroup).where(
        ModifierGroup.id == group_id,
        ModifierGroup.company_id == membership.company_id,
    ))
    if group is None:
        raise RecipeInputError(404, "Modifier group not found in this company.")
    option = ModifierOption(modifier_group_id=group.id, name=data.name)
    db.add(option)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise RecipeInputError(409, "A modifier option with this name already exists in the group.")
    db.refresh(option)
    return {"id": option.id, "modifier_group_id": group.id, "name": option.name, "is_active": option.is_active}


def create_recipe_version(db: Session, membership: CompanyMembership,
                          menu_product_id: UUID, data: RecipeVersionCreate) -> dict:
    # Lock the company catalogue row so concurrent version submissions do not
    # allocate the same next version number.
    product = db.scalar(select(Product).where(
        Product.id == menu_product_id,
        Product.company_id == membership.company_id,
        Product.product_kind == "MENU_ITEM",
        Product.is_active.is_(True),
    ).with_for_update())
    if product is None:
        raise RecipeInputError(404, "Active menu item not found in this company.")
    latest = db.scalar(select(RecipeVersion).where(
        RecipeVersion.company_id == membership.company_id,
        RecipeVersion.menu_product_id == product.id,
    ).order_by(RecipeVersion.version.desc()).limit(1))
    if latest and data.effective_from <= latest.effective_from:
        raise RecipeInputError(422, "A new recipe version must have an effective date after the latest version.")

    ingredient_ids = {line.ingredient_product_id for line in data.ingredients}
    ingredient_ids.update(line.ingredient_product_id for line in data.modifier_ingredients)
    ingredients = _ingredient_products(db, membership, ingredient_ids)
    for line in [*data.ingredients, *data.modifier_ingredients]:
        product_unit = ingredients[line.ingredient_product_id].unit_of_measure
        if line.unit.strip().casefold() != product_unit.strip().casefold():
            raise RecipeInputError(422,
                f"Unit '{line.unit}' is incompatible with ingredient '{ingredients[line.ingredient_product_id].product_name}' canonical unit '{product_unit}'. No unit conversion is applied.")

    option_ids = {line.modifier_option_id for line in data.modifier_ingredients}
    options = db.scalars(select(ModifierOption).join(
        ModifierGroup, ModifierGroup.id == ModifierOption.modifier_group_id,
    ).where(ModifierOption.id.in_(option_ids), ModifierOption.is_active.is_(True),
        ModifierGroup.company_id == membership.company_id,
        ModifierGroup.menu_product_id == product.id,
    )).all() if option_ids else []
    options_by_id = {option.id: option for option in options}
    if len(options_by_id) != len(option_ids):
        raise RecipeInputError(422, "Every modifier mapping must reference an active option on this menu item.")

    version = RecipeVersion(company_id=membership.company_id, menu_product_id=product.id,
        version=(latest.version + 1 if latest else 1), effective_from=data.effective_from)
    db.add(version)
    try:
        db.flush()
        db.add_all([RecipeIngredient(recipe_version_id=version.id,
            ingredient_product_id=line.ingredient_product_id, quantity=line.quantity,
            unit=ingredients[line.ingredient_product_id].unit_of_measure) for line in data.ingredients])
        db.add_all([ModifierRecipeIngredient(recipe_version_id=version.id,
            modifier_option_id=line.modifier_option_id,
            ingredient_product_id=line.ingredient_product_id, quantity=line.quantity,
            unit=ingredients[line.ingredient_product_id].unit_of_measure) for line in data.modifier_ingredients])
        db.commit()
    except IntegrityError:
        db.rollback()
        raise RecipeInputError(409, "A recipe version already exists for this menu item and effective date.")
    db.refresh(version)
    return recipe_version_view(db, version)
