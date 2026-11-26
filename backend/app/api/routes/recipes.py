from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_membership, require_roles
from app.db.session import get_db
from app.models import CompanyMembership
from app.schemas.recipe import (ModifierGroupCreate, ModifierOptionCreate,
    RecipeVersionCreate)
from app.services.recipes import (RecipeInputError, add_modifier_option,
    create_modifier_group, create_recipe_version, list_modifier_groups,
    list_recipe_menus, recipe_menu_detail, resolve_recipe_version,
    recipe_version_view)

router = APIRouter(tags=["Recipes and Modifiers"])


def _translate(error: RecipeInputError):
    raise HTTPException(status_code=error.status_code, detail=error.message)


@router.get("")
def get_recipe_menus(membership: CompanyMembership = Depends(get_current_membership),
                     db: Session = Depends(get_db)):
    return list_recipe_menus(db, membership)


@router.get("/menu-items/{menu_product_id}")
def get_recipe_menu(menu_product_id: UUID,
                    membership: CompanyMembership = Depends(get_current_membership),
                    db: Session = Depends(get_db)):
    try:
        return recipe_menu_detail(db, membership, menu_product_id)
    except RecipeInputError as error:
        _translate(error)


@router.get("/menu-items/{menu_product_id}/version-for-date")
def get_recipe_version_for_date(menu_product_id: UUID,
        business_date: date = Query(),
        membership: CompanyMembership = Depends(get_current_membership),
        db: Session = Depends(get_db)):
    try:
        version = resolve_recipe_version(db, membership, menu_product_id, business_date)
        return recipe_version_view(db, version) if version else None
    except RecipeInputError as error:
        _translate(error)


@router.post("/menu-items/{menu_product_id}/versions", status_code=status.HTTP_201_CREATED)
def post_recipe_version(menu_product_id: UUID, data: RecipeVersionCreate,
        membership: CompanyMembership = Depends(require_roles("OWNER")),
        db: Session = Depends(get_db)):
    try:
        return create_recipe_version(db, membership, menu_product_id, data)
    except RecipeInputError as error:
        _translate(error)


@router.get("/menu-items/{menu_product_id}/modifier-groups")
def get_modifier_groups(menu_product_id: UUID,
        membership: CompanyMembership = Depends(get_current_membership),
        db: Session = Depends(get_db)):
    try:
        return list_modifier_groups(db, membership, menu_product_id)
    except RecipeInputError as error:
        _translate(error)


@router.post("/menu-items/{menu_product_id}/modifier-groups", status_code=status.HTTP_201_CREATED)
def post_modifier_group(menu_product_id: UUID, data: ModifierGroupCreate,
        membership: CompanyMembership = Depends(require_roles("OWNER")),
        db: Session = Depends(get_db)):
    try:
        return create_modifier_group(db, membership, menu_product_id, data)
    except RecipeInputError as error:
        _translate(error)


@router.post("/modifier-groups/{group_id}/options", status_code=status.HTTP_201_CREATED)
def post_modifier_option(group_id: UUID, data: ModifierOptionCreate,
        membership: CompanyMembership = Depends(require_roles("OWNER")),
        db: Session = Depends(get_db)):
    try:
        return add_modifier_option(db, membership, group_id, data)
    except RecipeInputError as error:
        _translate(error)
