from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_membership, require_roles
from app.db.session import get_db
from app.models import (CompanyMembership, InventorySnapshot, ModifierGroup,
    ModifierRecipeIngredient, Product, ProductCategory, PurchaseLine,
    RecipeIngredient, RecipeVersion, SalesRecord)
from app.schemas.product import (CategoryCreate, CategoryResponse, ProductCreate,
    ProductKind, ProductResponse, ProductUpdate)

router = APIRouter(tags=["Products"])


def _category(db: Session, category_id: UUID | None, company_id: UUID):
    if category_id is None:
        return
    if db.scalar(select(ProductCategory).where(ProductCategory.id == category_id,
                                               ProductCategory.company_id == company_id)) is None:
        raise HTTPException(status_code=422, detail="Category does not belong to this company.")


def _validate_product_kind_change(db: Session, product: Product, new_kind: str) -> None:
    if product.product_kind == new_kind or product.product_kind == "LEGACY":
        return
    if product.product_kind == "MENU_ITEM" and new_kind != "MENU_ITEM":
        used = db.scalar(select(SalesRecord.id).where(SalesRecord.product_id == product.id).limit(1))
        recipe = db.scalar(select(RecipeVersion.id).where(RecipeVersion.menu_product_id == product.id).limit(1))
        modifiers = db.scalar(select(ModifierGroup.id).where(ModifierGroup.menu_product_id == product.id).limit(1))
        if used or recipe or modifiers:
            raise HTTPException(status_code=409, detail="A menu item used by sales, recipes or modifiers cannot be reclassified. Deactivate it instead.")
    if product.product_kind == "INGREDIENT" and new_kind != "INGREDIENT":
        used = db.scalar(select(PurchaseLine.id).where(PurchaseLine.product_id == product.id).limit(1))
        stock = db.scalar(select(InventorySnapshot.id).where(InventorySnapshot.product_id == product.id).limit(1))
        recipe = db.scalar(select(RecipeIngredient.id).where(RecipeIngredient.ingredient_product_id == product.id).limit(1))
        modifier = db.scalar(select(ModifierRecipeIngredient.id).where(ModifierRecipeIngredient.ingredient_product_id == product.id).limit(1))
        if used or stock or recipe or modifier:
            raise HTTPException(status_code=409, detail="An ingredient used by purchases, inventory or recipes cannot be reclassified. Deactivate it instead.")


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(data: ProductCreate, membership: CompanyMembership = Depends(require_roles("OWNER")), db: Session = Depends(get_db)):
    _category(db, data.category_id, membership.company_id)
    product = Product(company_id=membership.company_id, **data.model_dump())
    db.add(product)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A product with this SKU already exists.")
    db.refresh(product)
    return product


@router.get("", response_model=list[ProductResponse])
def list_products(search: str | None = Query(default=None, max_length=100),
                  category_id: UUID | None = None, include_inactive: bool = False,
                  product_kind: ProductKind | None = None,
                  membership: CompanyMembership = Depends(get_current_membership), db: Session = Depends(get_db)):
    query = select(Product).where(Product.company_id == membership.company_id)
    if search:
        query = query.where(Product.sku.ilike(f"%{search}%") | Product.product_name.ilike(f"%{search}%"))
    if category_id:
        query = query.where(Product.category_id == category_id)
    if product_kind:
        query = query.where(Product.product_kind == product_kind)
    if not include_inactive:
        query = query.where(Product.is_active.is_(True))
    return list(db.scalars(query.order_by(Product.product_name)).all())


@router.get("/categories", response_model=list[CategoryResponse])
def list_categories(membership: CompanyMembership = Depends(get_current_membership), db: Session = Depends(get_db)):
    return list(db.scalars(select(ProductCategory).where(ProductCategory.company_id == membership.company_id).order_by(ProductCategory.name)).all())


@router.post("/categories", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
def create_category(data: CategoryCreate, membership: CompanyMembership = Depends(require_roles("OWNER")), db: Session = Depends(get_db)):
    category = ProductCategory(company_id=membership.company_id, name=data.name.strip())
    db.add(category)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A category with this name already exists.")
    db.refresh(category)
    return category


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(product_id: UUID, membership: CompanyMembership = Depends(get_current_membership), db: Session = Depends(get_db)):
    product = db.scalar(select(Product).where(Product.id == product_id, Product.company_id == membership.company_id))
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    return product


@router.patch("/{product_id}", response_model=ProductResponse)
def update_product(product_id: UUID, data: ProductUpdate, membership: CompanyMembership = Depends(require_roles("OWNER")), db: Session = Depends(get_db)):
    product = db.scalar(select(Product).where(Product.id == product_id, Product.company_id == membership.company_id))
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    changes = data.model_dump(exclude_unset=True)
    _category(db, changes.get("category_id"), membership.company_id)
    if "product_kind" in changes:
        _validate_product_kind_change(db, product, changes["product_kind"])
    for key, value in changes.items():
        setattr(product, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A product with this SKU already exists.")
    db.refresh(product)
    return product
