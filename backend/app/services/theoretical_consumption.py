from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class UploadRef:
    id: UUID
    version: int


@dataclass(frozen=True)
class ProductRef:
    id: UUID
    company_id: UUID
    sku: str
    name: str
    kind: str
    unit: str
    is_active: bool


@dataclass(frozen=True)
class IngredientLine:
    product: ProductRef | None
    quantity: Decimal | None
    unit: str


@dataclass(frozen=True)
class RecipeRef:
    id: UUID
    company_id: UUID
    menu_product_id: UUID
    effective_from: date
    ingredients: tuple[IngredientLine, ...]


@dataclass(frozen=True)
class ModifierGroupRef:
    id: UUID
    company_id: UUID
    menu_product_id: UUID
    name: str
    selection_min: int
    selection_max: int


@dataclass(frozen=True)
class ModifierOptionRef:
    id: UUID
    group_id: UUID
    company_id: UUID
    menu_product_id: UUID


@dataclass(frozen=True)
class ModifierSelection:
    option: ModifierOptionRef | None
    selection_quantity: Decimal | None
    ingredients: tuple[IngredientLine, ...]


@dataclass(frozen=True)
class SaleInput:
    id: UUID
    company_id: UUID
    branch_id: UUID
    branch_name: str
    business_date: date
    product: ProductRef | None
    quantity: Decimal | None
    recipe_version_id: UUID | None
    recipe: RecipeRef | None
    modifier_groups: tuple[ModifierGroupRef, ...]
    modifiers: tuple[ModifierSelection, ...]
    source_upload: UploadRef


@dataclass(frozen=True)
class ScopeInput:
    company_id: UUID
    branch_id: UUID
    branch_name: str
    business_date: date
    uploads: tuple[UploadRef, ...]
    unavailable_reason: str | None = None


@dataclass
class _IngredientTotal:
    product: ProductRef
    base: Decimal = Decimal(0)
    modifier: Decimal = Decimal(0)
    has_base: bool = False
    has_modifier: bool = False
    base_invalid: bool = False
    modifier_invalid: bool = False
    reasons: set[str] = field(default_factory=set)
    uploads: set[UploadRef] = field(default_factory=set)


@dataclass
class _ScopeState:
    data: ScopeInput
    base_complete: bool = True
    modifier_complete: bool = True
    reasons: set[str] = field(default_factory=set)
    invalid_data: bool = False
    unit_mismatch: bool = False
    sales_count: int = 0


def _valid_positive(value: Decimal | None) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value > 0


def _scope_key(company_id: UUID, branch_id: UUID, business_date: date):
    return company_id, branch_id, business_date


def calculate_theoretical_consumption(
    scopes: tuple[ScopeInput, ...], sales: tuple[SaleInput, ...], company_id: UUID,
) -> dict:
    """Pure Decimal calculator. Database loading and tenant filtering live elsewhere."""
    scope_states = {
        _scope_key(scope.company_id, scope.branch_id, scope.business_date): _ScopeState(scope)
        for scope in scopes
    }
    totals: dict[tuple[UUID, UUID, date, UUID], _IngredientTotal] = {}
    unresolved: list[dict] = []

    def scope_for(sale: SaleInput) -> _ScopeState:
        key = _scope_key(sale.company_id, sale.branch_id, sale.business_date)
        if key not in scope_states:
            scope_states[key] = _ScopeState(ScopeInput(
                company_id=sale.company_id, branch_id=sale.branch_id,
                branch_name=sale.branch_name, business_date=sale.business_date,
                uploads=(sale.source_upload,),
            ))
        return scope_states[key]

    def issue(state: _ScopeState, sale: SaleInput, code: str,
              component: str = "both", ingredient: _IngredientTotal | None = None) -> None:
        state.reasons.add(code)
        if component in {"base", "both"}:
            state.base_complete = False
        if component in {"modifier", "both"}:
            state.modifier_complete = False
        if code == "UNIT_MISMATCH":
            state.unit_mismatch = True
        if code.startswith("INVALID_") or code.startswith("INVALID"):
            state.invalid_data = True
        if ingredient is not None:
            ingredient.reasons.add(code)
            if component in {"base", "both"}:
                ingredient.base_invalid = True
            if component in {"modifier", "both"}:
                ingredient.modifier_invalid = True

    def add_line(state: _ScopeState, sale: SaleInput, line: IngredientLine,
                 multiplier: Decimal, component: str, report_issue) -> None:
        product = line.product
        if product is None:
            report_issue("MISSING_INGREDIENT", component)
            return
        if product.company_id != company_id:
            report_issue("INVALID_INGREDIENT_RELATIONSHIP", component)
            return
        key = (sale.company_id, sale.branch_id, sale.business_date, product.id)
        total = totals.get(key)
        if total is None:
            total = _IngredientTotal(product=product)
            totals[key] = total
        total.uploads.add(sale.source_upload)
        if product.kind != "INGREDIENT":
            report_issue("INVALID_INGREDIENT_RELATIONSHIP", component, total)
            return
        if not product.is_active:
            report_issue("INACTIVE_INGREDIENT", component, total)
            return
        if not _valid_positive(line.quantity):
            report_issue("INVALID_RECIPE_QUANTITY", component, total)
            return
        if not line.unit.strip() or line.unit.strip().casefold() != product.unit.strip().casefold():
            report_issue("UNIT_MISMATCH", component, total)
            return
        amount = multiplier * line.quantity
        if not amount.is_finite() or amount < 0:
            report_issue("INVALID_CALCULATED_QUANTITY", component, total)
            return
        if component == "base":
            total.base += amount
            total.has_base = True
        else:
            total.modifier += amount
            total.has_modifier = True

    for sale in sales:
        if sale.company_id != company_id:
            continue
        state = scope_for(sale)
        state.sales_count += 1
        unresolved_reasons: set[str] = set()

        def sale_issue(code: str, component: str = "both",
                       ingredient: _IngredientTotal | None = None) -> None:
            issue(state, sale, code, component, ingredient)
            unresolved_reasons.add(code)

        product = sale.product
        if product is None or product.company_id != company_id or product.kind != "MENU_ITEM":
            sale_issue("INVALID_MENU_PRODUCT")
        if not _valid_positive(sale.quantity):
            sale_issue("INVALID_SALES_QUANTITY")

        recipe = sale.recipe
        if sale.recipe_version_id is None:
            sale_issue("MISSING_RECIPE_VERSION")
        elif recipe is None:
            sale_issue("INVALID_RECIPE_VERSION")
        elif (recipe.company_id != company_id or product is None
              or recipe.menu_product_id != product.id
              or recipe.effective_from > sale.business_date):
            sale_issue("INVALID_RECIPE_VERSION")
        elif not recipe.ingredients:
            sale_issue("MISSING_RECIPE_INGREDIENT_MAPPING", "base")
        elif product is not None and _valid_positive(sale.quantity):
            for line in recipe.ingredients:
                add_line(state, sale, line, sale.quantity, "base", sale_issue)
            if any(total.base_invalid for key, total in totals.items()
                   if key[:3] == (sale.company_id, sale.branch_id, sale.business_date)):
                # An invalid recipe line makes the base total incomplete for this scope.
                state.base_complete = False

        selected_by_group: dict[UUID, Decimal] = {}
        selections_valid = True
        configured_group_ids = {group.id for group in sale.modifier_groups}
        if product is not None:
            for group in sale.modifier_groups:
                if (group.company_id != company_id or group.menu_product_id != product.id
                        or group.selection_min < 0 or group.selection_max < group.selection_min):
                    sale_issue("INVALID_MODIFIER_GROUP")
                    selections_valid = False
                if group.selection_min != group.selection_max:
                    sale_issue("MODIFIER_COMPLETENESS_UNKNOWN", "modifier")

        for selection in sale.modifiers:
            option = selection.option
            if (option is None or product is None or option.company_id != company_id
                    or option.menu_product_id != product.id
                    or option.group_id not in configured_group_ids):
                sale_issue("INVALID_MODIFIER_RELATIONSHIP", "modifier")
                selections_valid = False
                continue
            selected_by_group[option.group_id] = selected_by_group.get(option.group_id, Decimal(0)) + (
                selection.selection_quantity if _valid_positive(selection.selection_quantity) else Decimal(0))
            if selection.selection_quantity is None:
                sale_issue("MISSING_MODIFIER_SELECTION_QUANTITY", "modifier")
                selections_valid = False
                continue
            if not _valid_positive(selection.selection_quantity):
                sale_issue("INVALID_MODIFIER_SELECTION_QUANTITY", "modifier")
                selections_valid = False
                continue
            if not selection.ingredients:
                # No explicit no-impact declaration exists in the current schema.
                sale_issue("MISSING_MODIFIER_INGREDIENT_MAPPING", "modifier")
                selections_valid = False
                continue
            if recipe is None or sale.recipe_version_id != recipe.id:
                sale_issue("INVALID_RECIPE_VERSION", "modifier")
                selections_valid = False
                continue
            for line in selection.ingredients:
                add_line(state, sale, line, selection.selection_quantity, "modifier", sale_issue)

        for group in sale.modifier_groups:
            selected = selected_by_group.get(group.id, Decimal(0))
            if group.selection_min == group.selection_max and _valid_positive(sale.quantity):
                expected = sale.quantity * group.selection_min
                if selected != expected:
                    sale_issue("MODIFIER_SELECTIONS_INCOMPLETE", "modifier")
                    selections_valid = False
        if sale.modifiers and not sale.modifier_groups:
            sale_issue("INVALID_MODIFIER_RELATIONSHIP", "modifier")
            selections_valid = False
        if not selections_valid:
            state.modifier_complete = False

        if unresolved_reasons:
            unresolved.append({
                "sales_record_id": sale.id,
                "branch_id": sale.branch_id,
                "business_date": sale.business_date,
                "reason_codes": sorted(unresolved_reasons),
                "source_upload_id": sale.source_upload.id,
                "source_upload_version": sale.source_upload.version,
            })

    items: list[dict] = []
    scopes_output: list[dict] = []
    for key, state in scope_states.items():
        data = state.data
        if data.unavailable_reason:
            status = "UNAVAILABLE"
            state.reasons.add(data.unavailable_reason)
        elif state.sales_count == 0:
            status = "UNAVAILABLE"
            state.reasons.add("NO_SALES_RECORDS")
        elif state.unit_mismatch:
            status = "UNIT_MISMATCH"
        elif state.invalid_data:
            status = "INVALID_DATA"
        elif not state.base_complete or not state.modifier_complete:
            status = "INCOMPLETE"
        else:
            status = "COMPLETE"
        scopes_output.append({
            "company_id": data.company_id,
            "branch_id": data.branch_id,
            "branch_name": data.branch_name,
            "business_date": data.business_date,
            "status": status,
            "reason_codes": sorted(state.reasons),
            "source_uploads": [{"upload_id": upload.id, "version": upload.version}
                               for upload in sorted(data.uploads, key=lambda x: (str(x.id), x.version))],
        })

    for (row_company, branch_id, business_date, ingredient_id), total in totals.items():
        state = scope_states[(row_company, branch_id, business_date)]
        # Expose known subtotals when useful, but never publish a total unless
        # every sale and modifier in the scope is complete.
        base_value = total.base if (total.has_base or state.base_complete) and not total.base_invalid else None
        modifier_value = total.modifier if (total.has_modifier or state.modifier_complete) and not total.modifier_invalid else None
        overall_value = (base_value + modifier_value
            if state.base_complete and state.modifier_complete
            and not total.base_invalid and not total.modifier_invalid
            and base_value is not None and modifier_value is not None else None)
        if "UNIT_MISMATCH" in total.reasons:
            status = "UNIT_MISMATCH"
        elif (base_value is None or modifier_value is None or state.invalid_data
              or state.unit_mismatch or state.reasons):
            status = "INCOMPLETE"
        else:
            status = "COMPLETE"
        items.append({
            "company_id": row_company,
            "branch_id": branch_id,
            "branch_name": state.data.branch_name,
            "business_date": business_date,
            "ingredient_id": ingredient_id,
            "ingredient_sku": total.product.sku,
            "ingredient_name": total.product.name,
            "canonical_unit": total.product.unit,
            "base_theoretical_consumption": base_value,
            "modifier_theoretical_consumption": modifier_value,
            "total_theoretical_consumption": overall_value,
            "status": status,
            "reason_codes": sorted(total.reasons | state.reasons),
            "source_uploads": [{"upload_id": upload.id, "version": upload.version}
                               for upload in sorted(total.uploads, key=lambda x: (str(x.id), x.version))],
        })

    return {"items": items, "scopes": scopes_output, "unresolved_sales": unresolved}
