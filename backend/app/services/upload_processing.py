from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (Branch, DailyUpload, InventorySnapshot, Product,
    PurchaseLine, SalesRecord, SalesRecordModifier, UploadValidationIssue,
    ModifierGroup, ModifierOption, RecipeVersion, PurchaseReceiptIdentity,
    PurchaseReceiptCurrentLine, StockMovement, StockMovementReasonCode,
    StockCoverageDeclaration)
from app.services.workbook import ParsedWorkbook, WorkbookIssue, normalize_date, read_workbook


def _as_date(value: object) -> date | None:
    return normalize_date(value)


def _fits_numeric_18_4(value: Decimal) -> bool:
    if not value.is_finite():
        return False
    normalized = value.normalize()
    scale = max(0, -normalized.as_tuple().exponent)
    integer_digits = max(1, normalized.adjusted() + 1) if value else 1
    return scale <= 4 and integer_digits + scale <= 18


def _issue(result: ParsedWorkbook, severity: str, sheet: str, row: int | None, code: str, message: str) -> None:
    result.issues.append(WorkbookIssue(severity, sheet, row, code, message))


def _validations(db: Session, upload: DailyUpload, branch: Branch, content: bytes) -> ParsedWorkbook:
    result = read_workbook(content)
    workbook_date = normalize_date(result.metadata.get("business date"))
    upload_date = normalize_date(upload.business_date)
    if workbook_date != upload_date:
        _issue(result, "ERROR", "Metadata", None, "BUSINESS_DATE_MISMATCH", "Workbook Business Date must match the upload date.")
    branch_reference = result.metadata.get("branch reference", "").strip()
    if branch_reference not in {str(branch.id), branch.code or ""}:
        _issue(result, "ERROR", "Metadata", None, "BRANCH_MISMATCH", "Workbook Branch Reference does not match the selected branch.")
    # Workbook metadata is cross-checked; company identity always comes from the authenticated upload.
    from app.models import Company
    company = db.get(Company, branch.company_id)
    if company and result.metadata.get("currency", "").upper() != company.currency.upper():
        _issue(result, "ERROR", "Metadata", None, "CURRENCY_MISMATCH", "Workbook Currency must match the company's configured currency.")
    granularity = result.metadata.get("source granularity", "").upper()
    if granularity not in {"TRANSACTION", "AGGREGATED"}:
        return result
    template_version = result.metadata.get("template version")
    is_v3 = template_version == "3.0"
    is_cafe = template_version in {"2.0", "3.0"}
    product_map = {p.sku: p for p in db.scalars(select(Product).where(Product.company_id == upload.company_id)).all()}
    sku_rows = {
        "Daily Sales": "SKU", "Inventory": "SKU", "Purchases": "SKU",
    }
    for sheet_name, sku_column in sku_rows.items():
        for index, row in enumerate(result.rows.get(sheet_name, []), start=2):
            sku = str(row.get(sku_column) or "").strip()
            product = product_map.get(sku)
            if not sku:
                _issue(result, "ERROR", sheet_name, index, "MISSING_SKU", "SKU is required.")
            elif product is None:
                _issue(result, "ERROR", sheet_name, index, "UNKNOWN_SKU", f"SKU '{sku}' is not in this company's product catalogue.")
            elif not product.is_active:
                _issue(result, "ERROR", sheet_name, index, "INACTIVE_SKU", f"SKU '{sku}' is inactive and cannot be used for new data.")
            elif is_cafe and sheet_name == "Daily Sales" and product.product_kind != "MENU_ITEM":
                _issue(result, "ERROR", sheet_name, index, "INCORRECT_PRODUCT_KIND", f"SKU '{sku}' must be classified as MENU_ITEM for template 2.0 Daily Sales.")
            elif is_cafe and sheet_name in {"Inventory", "Purchases"} and product.product_kind != "INGREDIENT":
                _issue(result, "ERROR", sheet_name, index, "INCORRECT_PRODUCT_KIND", f"SKU '{sku}' must be classified as INGREDIENT for template 2.0 {sheet_name}.")
            elif sheet_name == "Inventory" and str(row.get("Unit") or "").strip().casefold() != product.unit_of_measure.casefold():
                _issue(result, "ERROR", sheet_name, index, "UNIT_MISMATCH", f"Unit does not match the product catalogue unit '{product.unit_of_measure}'.")
            if product is not None and is_cafe and sheet_name == "Purchases" and str(row.get("Purchase Unit") or "").strip().casefold() != product.unit_of_measure.casefold():
                _issue(result, "ERROR", sheet_name, index, "UNIT_MISMATCH", f"Purchase Unit must match the ingredient's canonical unit '{product.unit_of_measure}'. No unit conversion is applied.")

    if is_cafe:
        sales_by_ref: dict[str, dict] = {}
        for index, row in enumerate(result.rows.get("Daily Sales", []), start=2):
            reference = str(row.get("Sales Row Reference") or "").strip()
            if reference in sales_by_ref:
                _issue(result, "ERROR", "Daily Sales", index, "DUPLICATE_SALES_ROW_REFERENCE", "Sales Row Reference must be unique within the workbook.")
            else:
                sales_by_ref[reference] = row
            product = product_map.get(str(row.get("SKU") or "").strip())
            if product is None or product.product_kind != "MENU_ITEM":
                continue
            recipe = db.scalar(select(RecipeVersion).where(
                RecipeVersion.company_id == upload.company_id,
                RecipeVersion.menu_product_id == product.id,
                RecipeVersion.effective_from <= upload.business_date,
            ).order_by(RecipeVersion.effective_from.desc()).limit(1))
            if recipe is None:
                _issue(result, "ERROR", "Daily Sales", index, "MISSING_RECIPE_VERSION", "No recipe version is effective for this menu item on the business date.")
            else:
                row["__recipe_version_id"] = recipe.id

        groups = db.scalars(select(ModifierGroup).where(ModifierGroup.company_id == upload.company_id)).all()
        groups_by_menu_name = {(group.menu_product_id, group.name.strip().casefold()): group for group in groups}
        options = db.scalars(select(ModifierOption).join(ModifierGroup).where(ModifierGroup.company_id == upload.company_id)).all()
        options_by_group_name = {(option.modifier_group_id, option.name.strip().casefold()): option for option in options}
        selected_totals: dict[tuple[str, object], Decimal] = {}
        selected_options: set[tuple[str, object]] = set()
        for index, modifier in enumerate(result.rows.get("Sales Modifiers", []), start=2):
            reference = str(modifier.get("Sales Row Reference") or "").strip()
            sale = sales_by_ref.get(reference)
            if sale is None:
                _issue(result, "ERROR", "Sales Modifiers", index, "UNKNOWN_SALES_ROW_REFERENCE", "Sales Row Reference does not identify a Daily Sales row in this workbook.")
                continue
            product = product_map.get(str(sale.get("SKU") or "").strip())
            group = groups_by_menu_name.get((product.id, str(modifier.get("Modifier Group") or "").strip().casefold())) if product else None
            if group is None:
                _issue(result, "ERROR", "Sales Modifiers", index, "UNKNOWN_MODIFIER_GROUP", "Modifier Group is not configured for this menu item.")
                continue
            option = options_by_group_name.get((group.id, str(modifier.get("Modifier Option") or "").strip().casefold()))
            if option is None or not option.is_active:
                _issue(result, "ERROR", "Sales Modifiers", index, "UNKNOWN_MODIFIER_OPTION", "Modifier Option is not active in the selected group.")
                continue
            key = (reference, option.id)
            if key in selected_options:
                _issue(result, "ERROR", "Sales Modifiers", index, "DUPLICATE_MODIFIER_SELECTION", "A modifier option can appear only once per sales row; combine its Selection Quantity.")
                continue
            selected_options.add(key)
            quantity = modifier.get("Selection Quantity")
            selected_totals[(reference, group.id)] = selected_totals.get((reference, group.id), Decimal(0)) + quantity
            modifier["__modifier_option_id"] = option.id
        for reference, sale in sales_by_ref.items():
            product = product_map.get(str(sale.get("SKU") or "").strip())
            if product is None:
                continue
            quantity = sale.get("Quantity") or Decimal(0)
            for group in (item for item in groups if item.menu_product_id == product.id):
                selected = selected_totals.get((reference, group.id), Decimal(0))
                minimum = quantity * group.selection_min
                maximum = quantity * group.selection_max
                if selected < minimum or selected > maximum:
                    _issue(result, "ERROR", "Sales Modifiers", None, "MODIFIER_SELECTION_COUNT_MISMATCH", f"Modifier group '{group.name}' requires {minimum} to {maximum} selections for sales row '{reference}'; received {selected}.")
    business_date = upload.business_date
    for index, row in enumerate(result.rows.get("Daily Sales", []), start=2):
        tx_at = row.get("Transaction DateTime")
        if isinstance(tx_at, datetime) and tx_at.date() != business_date:
            _issue(result, "ERROR", "Daily Sales", index, "TRANSACTION_DATE_MISMATCH", "Transaction date must match the workbook business date.")
    for index, row in enumerate(result.rows.get("Inventory", []), start=2):
        for column in (
            "Opening Quantity",
            "Closing Quantity",
            "Damaged Quantity",
            "Wasted Quantity",
            "Staff Consumption Quantity",
        ):
            value = row.get(column)
            if value is not None and value < 0:
                _issue(result, "ERROR", "Inventory", index, "NEGATIVE_INVENTORY", f"{column} cannot be negative.")
        expiry = _as_date(row.get("Expiry Date"))
        if row.get("Expiry Date") not in (None, "") and expiry is None:
            _issue(result, "ERROR", "Inventory", index, "INVALID_EXPIRY_DATE", "Expiry Date must be a valid date.")
    seen_receipts: set[tuple[str, str]] = set()
    seen_receipt_events: set[str] = set()
    for index, row in enumerate(result.rows.get("Purchases", []), start=2):
        identity = (str(row.get("Receipt ID") or "").strip(), str(row.get("Receipt Line ID") or "").strip())
        if identity in seen_receipts and not is_v3:
            _issue(result, "ERROR", "Purchases", index, "DUPLICATE_PURCHASE_LINE", "Receipt ID and Receipt Line ID are duplicated in this workbook.")
        seen_receipts.add(identity)
        if not isinstance(row.get("Quantity Received"), Decimal) or row["Quantity Received"] <= 0:
            _issue(result, "ERROR", "Purchases", index, "INVALID_PURCHASE_QUANTITY", "Quantity Received must be greater than zero.")
        if is_v3 and isinstance(row.get("Quantity Received"), Decimal) and not _fits_numeric_18_4(row["Quantity Received"]):
            _issue(result, "ERROR", "Purchases", index, "INVALID_PURCHASE_QUANTITY_PRECISION", "Quantity Received must fit the database precision of 18 digits with up to 4 decimal places.")
        if row.get("Unit Purchase Price") is not None and row["Unit Purchase Price"] < 0:
            _issue(result, "ERROR", "Purchases", index, "INVALID_PURCHASE_PRICE", "Unit Purchase Price cannot be negative.")
        if _as_date(row.get("Receipt Date")) is None:
            _issue(result, "ERROR", "Purchases", index, "INVALID_RECEIPT_DATE", "Receipt Date must be a valid date.")
        expiry = _as_date(row.get("Expiry Date"))
        if row.get("Expiry Date") not in (None, "") and expiry is None:
            _issue(result, "ERROR", "Purchases", index, "INVALID_EXPIRY_DATE", "Expiry Date must be a valid date.")

        if is_v3:
            event_id = str(row.get("Receipt Event ID") or "").strip()
            product = product_map.get(str(row.get("SKU") or "").strip())
            if str(row.get("Batch Number") or "").strip() and len(str(row["Batch Number"]).strip()) > 120:
                _issue(result, "ERROR", "Purchases", index, "INVALID_BATCH_NUMBER", "Batch Number cannot exceed 120 characters.")
            if not event_id:
                _issue(result, "ERROR", "Purchases", index, "MISSING_RECEIPT_EVENT_ID", "Receipt Event ID is required in template 3.0.")
            elif event_id in seen_receipt_events:
                _issue(result, "ERROR", "Purchases", index, "DUPLICATE_RECEIPT_EVENT_ID", "Receipt Event ID must identify one physical receipt event per workbook.")
            else:
                seen_receipt_events.add(event_id)
            if product is not None and str(row.get("Purchase Unit") or "").strip().casefold() != product.unit_of_measure.casefold():
                _issue(result, "ERROR", "Purchases", index, "UNVERIFIED_PURCHASE_UNIT", "A purchase receipt movement requires a Purchase Unit matching the ingredient's canonical unit.")
            if event_id and product is not None and str(row.get("Purchase Unit") or "").strip().casefold() == product.unit_of_measure.casefold():
                receipt_reason = db.get(StockMovementReasonCode,
                    ("RECEIVED_FROM_SUPPLIER", "PURCHASE_RECEIPT"))
                if receipt_reason is None or not receipt_reason.is_active:
                    _issue(result, "ERROR", "Purchases", index, "PURCHASE_RECEIPT_REASON_UNAVAILABLE", "The configured purchase receipt reason is unavailable; no confirmed receipt movement can be created.")
            if event_id and product is not None:
                receipt_identity = db.scalar(select(PurchaseReceiptIdentity).where(
                    PurchaseReceiptIdentity.company_id == upload.company_id,
                    PurchaseReceiptIdentity.branch_id == upload.branch_id,
                    PurchaseReceiptIdentity.receipt_event_id == event_id,
                ))
                if receipt_identity is not None:
                    prior_lines = db.execute(select(PurchaseLine.product_id,
                        DailyUpload.business_date).join(DailyUpload,
                        DailyUpload.id == PurchaseLine.source_upload_id).where(
                            PurchaseLine.receipt_identity_id == receipt_identity.id,
                            PurchaseLine.company_id == upload.company_id,
                            PurchaseLine.branch_id == upload.branch_id,
                        )).all()
                    if any(prior_date != upload.business_date or prior_product_id != product.id
                           for prior_product_id, prior_date in prior_lines):
                        _issue(result, "ERROR", "Purchases", index, "RECEIPT_EVENT_ID_REUSED",
                            "Receipt Event ID is already tied to a different business date or ingredient in this branch.")

    if is_v3:
        allowed_manual_types = {
            "OTHER_INFLOW", "POSITIVE_ADJUSTMENT", "WASTE", "STAFF_CONSUMPTION",
            "DAMAGE", "NEGATIVE_ADJUSTMENT", "OTHER_OUTFLOW",
        }
        allowed_coverage_dimensions = {
            "INGREDIENT", "BATCH", "OPENING_STOCK", "CLOSING_STOCK", "MOVEMENT_CATEGORY",
        }
        allowed_coverage_scopes = {"INGREDIENT", "ALL_BATCHES", "BATCH"}
        allowed_coverage_statuses = {
            "COMPLETE", "PARTIAL", "UNREPORTED", "NOT_APPLICABLE", "NO_STOCK",
        }
        allowed_coverage_movement_types = {
            "PURCHASE_RECEIPT", "OTHER_INFLOW", "POSITIVE_ADJUSTMENT", "TRANSFER_IN",
            "WASTE", "STAFF_CONSUMPTION", "DAMAGE", "NEGATIVE_ADJUSTMENT",
            "OTHER_OUTFLOW", "TRANSFER_OUT",
        }
        seen_physical_events: set[UUID] = set()
        batch_context: dict[str, set[str]] = {}
        inventory_rows_by_scope: dict[tuple[str, str], dict] = {}
        for inventory_row in result.rows.get("Inventory", []):
            sku = str(inventory_row.get("SKU") or "").strip()
            batch = str(inventory_row.get("Batch Number") or "").strip()
            inventory_rows_by_scope[(sku, batch)] = inventory_row
            if batch:
                batch_context.setdefault(sku, set()).add(batch)
        for sheet_name, sku_column in (("Purchases", "SKU"), ("Stock Movements", "Ingredient SKU")):
            for context_row in result.rows.get(sheet_name, []):
                sku = str(context_row.get(sku_column) or "").strip()
                batch = str(context_row.get("Batch Number") or "").strip()
                if sku and batch:
                    batch_context.setdefault(sku, set()).add(batch)

        for index, row in enumerate(result.rows.get("Stock Movements", []), start=2):
            sku = str(row.get("Ingredient SKU") or "").strip()
            product = product_map.get(sku)
            if not sku:
                _issue(result, "ERROR", "Stock Movements", index, "MISSING_SKU", "Ingredient SKU is required.")
            elif product is None:
                _issue(result, "ERROR", "Stock Movements", index, "UNKNOWN_SKU", f"SKU '{sku}' is not in this company's product catalogue.")
            elif not product.is_active or product.product_kind != "INGREDIENT":
                _issue(result, "ERROR", "Stock Movements", index, "INCORRECT_PRODUCT_KIND", f"SKU '{sku}' must be an active INGREDIENT.")
            unit = str(row.get("Unit") or "").strip()
            if product is not None and unit != product.unit_of_measure:
                _issue(result, "ERROR", "Stock Movements", index, "UNIT_MISMATCH", f"Unit must exactly match the ingredient's canonical unit '{product.unit_of_measure}'.")
            movement_type = str(row.get("Movement Type") or "").strip().upper()
            if movement_type not in allowed_manual_types:
                _issue(result, "ERROR", "Stock Movements", index, "INVALID_MOVEMENT_TYPE", "Movement Type must be a supported non-purchase, non-transfer movement.")
            movement_date = _as_date(row.get("Movement Date"))
            if movement_date is None:
                _issue(result, "ERROR", "Stock Movements", index, "INVALID_MOVEMENT_DATE", "Movement Date must be a valid date.")
            elif movement_date != upload.business_date:
                _issue(result, "ERROR", "Stock Movements", index, "MOVEMENT_DATE_MISMATCH", "Movement Date must match the upload business date.")
            quantity = row.get("Quantity")
            if not isinstance(quantity, Decimal) or quantity <= 0:
                _issue(result, "ERROR", "Stock Movements", index, "INVALID_MOVEMENT_QUANTITY", "Quantity must be greater than zero.")
            elif not _fits_numeric_18_4(quantity):
                _issue(result, "ERROR", "Stock Movements", index, "INVALID_MOVEMENT_QUANTITY_PRECISION", "Quantity must fit the database precision of 18 digits with up to 4 decimal places.")
            raw_event_id = str(row.get("Physical Event ID") or "").strip()
            try:
                event_id = UUID(raw_event_id)
                row["__physical_event_id"] = event_id
            except (ValueError, TypeError, AttributeError):
                event_id = None
                _issue(result, "ERROR", "Stock Movements", index, "INVALID_PHYSICAL_EVENT_ID", "Physical Event ID must be a UUID and remain stable across corrections.")
            if event_id is not None:
                if event_id in seen_physical_events:
                    _issue(result, "ERROR", "Stock Movements", index, "DUPLICATE_PHYSICAL_EVENT_ID", "Physical Event ID can appear only once per upload.")
                seen_physical_events.add(event_id)
                previous_rows = db.execute(select(StockMovement, DailyUpload.business_date).outerjoin(
                    DailyUpload, DailyUpload.id == StockMovement.source_upload_id).where(
                        StockMovement.company_id == upload.company_id,
                        StockMovement.branch_id == upload.branch_id,
                        StockMovement.physical_event_id == event_id,
                )).all()
                for previous, previous_date in previous_rows:
                    if (previous.origin_type != "UPLOAD" or previous_date != upload.business_date
                            or previous.movement_type != movement_type
                            or (product is not None and previous.ingredient_product_id != product.id)):
                        _issue(result, "ERROR", "Stock Movements", index,
                            "PHYSICAL_EVENT_ID_REUSED", "Physical Event ID is already tied to a different event in this branch.")
                        break
            batch = str(row.get("Batch Number") or "").strip()
            if len(batch) > 120:
                _issue(result, "ERROR", "Stock Movements", index, "INVALID_BATCH_NUMBER", "Batch Number cannot exceed 120 characters.")
            if product is not None and batch:
                batch_context.setdefault(sku, set()).add(batch)
            reason_code = str(row.get("Reason Code") or "").strip()
            reason = db.get(StockMovementReasonCode, (reason_code, movement_type)) if reason_code and movement_type in allowed_manual_types else None
            if reason is None or not reason.is_active:
                _issue(result, "ERROR", "Stock Movements", index, "INVALID_MOVEMENT_REASON", "Reason Code must be active and match Movement Type.")
            reason_detail = str(row.get("Reason Detail") or "").strip()
            if len(reason_detail) > 500:
                _issue(result, "ERROR", "Stock Movements", index, "INVALID_MOVEMENT_REASON_DETAIL", "Reason Detail cannot exceed 500 characters.")
            requires_detail = (movement_type in {"POSITIVE_ADJUSTMENT", "NEGATIVE_ADJUSTMENT"}
                or reason_code.startswith("OTHER_") or reason_code.endswith("_OTHER"))
            if requires_detail and not reason_detail:
                _issue(result, "ERROR", "Stock Movements", index, "MISSING_MOVEMENT_REASON_DETAIL", "Reason Detail is required for adjustments and 'other' reasons.")

        coverage_keys: set[tuple[str, str, str, str, str]] = set()
        coverage_scopes: dict[tuple[str, str], set[str]] = {}
        for index, row in enumerate(result.rows.get("Stock Coverage", []), start=2):
            sku = str(row.get("Ingredient SKU") or "").strip()
            product = product_map.get(sku)
            if not sku:
                _issue(result, "ERROR", "Stock Coverage", index, "MISSING_SKU", "Ingredient SKU is required.")
            elif product is None:
                _issue(result, "ERROR", "Stock Coverage", index, "UNKNOWN_SKU", f"SKU '{sku}' is not in this company's product catalogue.")
            elif not product.is_active or product.product_kind != "INGREDIENT":
                _issue(result, "ERROR", "Stock Coverage", index, "INCORRECT_PRODUCT_KIND", f"SKU '{sku}' must be an active INGREDIENT.")
            unit = str(row.get("Unit") or "").strip()
            if product is not None and unit != product.unit_of_measure:
                _issue(result, "ERROR", "Stock Coverage", index, "UNIT_MISMATCH", f"Unit must exactly match the ingredient's canonical unit '{product.unit_of_measure}'.")
            dimension = str(row.get("Coverage Dimension") or "").strip().upper()
            scope = str(row.get("Scope Type") or "").strip().upper()
            batch = str(row.get("Batch Number") or "").strip()
            if len(batch) > 120:
                _issue(result, "ERROR", "Stock Coverage", index, "INVALID_BATCH_NUMBER", "Batch Number cannot exceed 120 characters.")
            movement_type = str(row.get("Movement Type") or "").strip().upper()
            status = str(row.get("Status") or "").strip().upper()
            if dimension not in allowed_coverage_dimensions:
                _issue(result, "ERROR", "Stock Coverage", index, "INVALID_COVERAGE_DIMENSION", "Coverage Dimension is not supported.")
            if scope not in allowed_coverage_scopes:
                _issue(result, "ERROR", "Stock Coverage", index, "INVALID_COVERAGE_SCOPE", "Scope Type must be INGREDIENT, ALL_BATCHES or BATCH.")
            if status not in allowed_coverage_statuses:
                _issue(result, "ERROR", "Stock Coverage", index, "INVALID_COVERAGE_STATUS", "Status must be COMPLETE, PARTIAL, UNREPORTED, NOT_APPLICABLE or NO_STOCK.")
            if dimension == "INGREDIENT" and scope != "INGREDIENT":
                _issue(result, "ERROR", "Stock Coverage", index, "INVALID_COVERAGE_SCOPE", "INGREDIENT coverage requires INGREDIENT scope.")
            if dimension == "BATCH" and scope != "ALL_BATCHES":
                _issue(result, "ERROR", "Stock Coverage", index, "INVALID_COVERAGE_SCOPE", "BATCH coverage requires ALL_BATCHES scope.")
            if scope == "BATCH" and not batch:
                _issue(result, "ERROR", "Stock Coverage", index, "MISSING_COVERAGE_BATCH", "BATCH scope requires a Batch Number.")
            if scope != "BATCH" and batch:
                _issue(result, "ERROR", "Stock Coverage", index, "UNEXPECTED_COVERAGE_BATCH", "Batch Number is allowed only with BATCH scope.")
            if scope == "BATCH" and batch and batch not in batch_context.get(sku, set()):
                _issue(result, "ERROR", "Stock Coverage", index, "UNKNOWN_COVERAGE_BATCH", "Batch Number must exist in Inventory, Purchases or Stock Movements in this workbook.")
            if dimension == "MOVEMENT_CATEGORY":
                if movement_type not in allowed_coverage_movement_types:
                    _issue(result, "ERROR", "Stock Coverage", index, "MISSING_COVERAGE_MOVEMENT_TYPE", "MOVEMENT_CATEGORY coverage requires a supported Movement Type.")
            elif movement_type:
                _issue(result, "ERROR", "Stock Coverage", index, "UNEXPECTED_COVERAGE_MOVEMENT_TYPE", "Movement Type is allowed only for MOVEMENT_CATEGORY coverage.")
            if status == "NO_STOCK" and dimension not in {"INGREDIENT", "BATCH", "OPENING_STOCK", "CLOSING_STOCK"}:
                _issue(result, "ERROR", "Stock Coverage", index, "INVALID_NO_STOCK_STATUS", "NO_STOCK is not valid for this coverage dimension.")

            key = (sku, dimension, scope, batch if scope == "BATCH" else "", movement_type if dimension == "MOVEMENT_CATEGORY" else "")
            if key in coverage_keys:
                _issue(result, "ERROR", "Stock Coverage", index, "DUPLICATE_COVERAGE_DECLARATION", "Coverage scope and dimension may be declared only once per upload.")
            coverage_keys.add(key)
            scopes = coverage_scopes.setdefault((sku, dimension), set())
            if scope in {"INGREDIENT", "ALL_BATCHES"} and any(
                old_scope == "BATCH" for old_scope in scopes
            ) or scope == "BATCH" and scopes.intersection({"INGREDIENT", "ALL_BATCHES"}):
                _issue(result, "ERROR", "Stock Coverage", index, "CONTRADICTORY_COVERAGE_SCOPE", "A broad scope cannot be combined with specific batch scopes for the same ingredient and dimension.")
            scopes.add(scope)

            if status == "COMPLETE" and dimension in {"INGREDIENT", "BATCH", "OPENING_STOCK", "CLOSING_STOCK"}:
                matching_inventory = [inventory_row for (inventory_sku, inventory_batch), inventory_row
                    in inventory_rows_by_scope.items() if inventory_sku == sku and
                    (scope != "BATCH" or inventory_batch == batch)]
                if not matching_inventory:
                    _issue(result, "ERROR", "Stock Coverage", index, "INCOMPLETE_COVERAGE_DECLARATION", "COMPLETE stock coverage requires the declared inventory scope to be present in the workbook; use NO_STOCK when explicitly empty.")
                if scope in {"INGREDIENT", "ALL_BATCHES"}:
                    known_batches = batch_context.get(sku, set())
                    reported_batches = {inventory_batch for inventory_sku, inventory_batch
                        in inventory_rows_by_scope if inventory_sku == sku and inventory_batch}
                    if known_batches - reported_batches:
                        _issue(result, "ERROR", "Stock Coverage", index, "INCOMPLETE_BATCH_COVERAGE", "COMPLETE coverage must include every batch referenced elsewhere in this workbook.")
            if status == "UNREPORTED" and dimension in {"INGREDIENT", "BATCH", "OPENING_STOCK", "CLOSING_STOCK"}:
                has_snapshot = any(inventory_sku == sku and
                    (scope != "BATCH" or inventory_batch == batch)
                    for inventory_sku, inventory_batch in inventory_rows_by_scope)
                if has_snapshot:
                    _issue(result, "ERROR", "Stock Coverage", index, "CONTRADICTORY_UNREPORTED_COVERAGE", "UNREPORTED coverage cannot be declared for a scope that has inventory rows in this workbook.")
            if status in {"UNREPORTED", "NOT_APPLICABLE"} and dimension == "MOVEMENT_CATEGORY":
                has_reported_movement = any(
                    str(movement.get("Ingredient SKU") or "").strip() == sku
                    and str(movement.get("Movement Type") or "").strip().upper() == movement_type
                    and (scope != "BATCH" or str(movement.get("Batch Number") or "").strip() == batch)
                    for movement in result.rows.get("Stock Movements", []))
                has_reported_purchase = movement_type == "PURCHASE_RECEIPT" and any(
                    str(purchase.get("SKU") or "").strip() == sku
                    and (scope != "BATCH" or str(purchase.get("Batch Number") or "").strip() == batch)
                    for purchase in result.rows.get("Purchases", []))
                if has_reported_movement or has_reported_purchase:
                    _issue(result, "ERROR", "Stock Coverage", index, "CONTRADICTORY_MOVEMENT_COVERAGE", f"{status} movement coverage cannot be declared when matching movement rows are present.")
            if status == "NO_STOCK" and dimension in {"INGREDIENT", "BATCH", "OPENING_STOCK", "CLOSING_STOCK"}:
                quantity_column = {"OPENING_STOCK": "Opening Quantity", "CLOSING_STOCK": "Closing Quantity"}.get(dimension)
                matching_rows = [inventory_row for (inventory_sku, inventory_batch), inventory_row
                    in inventory_rows_by_scope.items() if inventory_sku == sku and
                    (scope != "BATCH" or inventory_batch == batch)]
                if dimension in {"INGREDIENT", "BATCH"}:
                    has_stock = any((inventory_row.get("Opening Quantity") or Decimal(0)) > 0
                        or (inventory_row.get("Closing Quantity") or Decimal(0)) > 0
                        for inventory_row in result.rows.get("Inventory", [])
                        if str(inventory_row.get("SKU") or "").strip() == sku and
                        (scope != "BATCH" or str(inventory_row.get("Batch Number") or "").strip() == batch))
                else:
                    has_stock = any((inventory_row.get(quantity_column) or Decimal(0)) > 0
                        for inventory_row in matching_rows)
                if has_stock:
                    _issue(result, "ERROR", "Stock Coverage", index, "CONTRADICTORY_NO_STOCK", "NO_STOCK cannot be declared when the scoped inventory contains a positive quantity.")

    # Reconciliation is advisory: aggregate movement is not enough to infer batch-level stock movements.
    inventory_by_sku: dict[str, dict[str, Decimal]] = {}
    for row in result.rows.get("Inventory", []):
        sku = str(row.get("SKU") or "").strip()
        totals = inventory_by_sku.setdefault(sku, {key: Decimal(0) for key in ("opening", "closing", "damaged", "wasted", "adjustment")})
        for key, column in (("opening", "Opening Quantity"), ("closing", "Closing Quantity"),
                            ("damaged", "Damaged Quantity"), ("wasted", "Wasted Quantity"),
                            ("adjustment", "Adjustment Quantity")):
            totals[key] += row.get(column) or Decimal(0)
    purchases_by_sku: dict[str, Decimal] = {}
    for row in result.rows.get("Purchases", []):
        sku = str(row.get("SKU") or "").strip()
        purchases_by_sku[sku] = purchases_by_sku.get(sku, Decimal(0)) + (row.get("Quantity Received") or Decimal(0))
    sales_by_sku: dict[str, Decimal] = {}
    for row in result.rows.get("Daily Sales", []):
        sku = str(row.get("SKU") or "").strip()
        sales_by_sku[sku] = sales_by_sku.get(sku, Decimal(0)) + (row.get("Quantity") or Decimal(0))
    for sku, totals in inventory_by_sku.items():
        # Adjustment Quantity is a signed net stock movement here: positive
        # adds stock and negative removes stock. Do not reject negative values.
        expected = totals["opening"] + purchases_by_sku.get(sku, Decimal(0)) - sales_by_sku.get(sku, Decimal(0)) + totals["adjustment"] - totals["damaged"] - totals["wasted"]
        if abs(expected - totals["closing"]) > Decimal("0.0001"):
            _issue(result, "WARNING", "Inventory", None, "INVENTORY_RECONCILIATION", f"SKU '{sku}' closes at {totals['closing']} but listed movements imply {expected}. Review returns, transfers and adjustments.")
    return result


def process_upload(db: Session, upload: DailyUpload, branch: Branch, content: bytes) -> DailyUpload:
    # Serialize promotions for this branch so competing versions cannot both become current.
    db.scalar(select(Branch).where(Branch.id == branch.id).with_for_update())
    current_upload = db.scalar(select(DailyUpload).where(
        DailyUpload.branch_id == upload.branch_id,
        DailyUpload.business_date == upload.business_date,
        DailyUpload.is_current.is_(True),
    ).with_for_update())
    if current_upload is not None and current_upload.version > upload.version:
        upload.processing_status = "SKIPPED"
        upload.processing_completed_at = datetime.now().astimezone()
        db.commit()
        db.refresh(upload)
        return upload

    # A completed current upload is immutable. Returning it makes retries safe
    # and avoids rewriting structured rows or any future upload-derived records.
    if upload.processing_status == "COMPLETED" and upload.is_current:
        return upload

    upload.processing_status = "VALIDATING"
    upload.processing_started_at = datetime.now().astimezone()
    db.execute(delete(UploadValidationIssue).where(UploadValidationIssue.upload_id == upload.id))
    result = _validations(db, upload, branch, content)
    rows_read = sum(len(v) for v in result.rows.values())
    errors = [issue for issue in result.issues if issue.severity == "ERROR"]
    warnings = [issue for issue in result.issues if issue.severity == "WARNING"]
    for issue in result.issues:
        db.add(UploadValidationIssue(upload_id=upload.id, severity=issue.severity,
            sheet=issue.sheet or "Workbook", row_number=issue.row, code=issue.code, message=issue.message))
    upload.rows_read = rows_read
    upload.rows_accepted = 0 if errors else rows_read
    upload.rows_rejected = sum(1 for issue in errors if issue.row is not None)
    upload.error_count = len(errors)
    upload.warning_count = len(warnings)
    upload.processing_completed_at = datetime.now().astimezone()
    if errors:
        upload.processing_status = "VALIDATION_FAILED"
        db.commit()
        db.refresh(upload)
        return upload

    try:
        products = {p.sku: p for p in db.scalars(select(Product).where(Product.company_id == upload.company_id)).all()}
        # Retain sales, modifiers, inventory and purchase source rows as
        # immutable evidence tied to their exact upload version. Current
        # analytics select only the completed upload marked is_current below.
        old_current = db.scalars(select(DailyUpload).where(DailyUpload.branch_id == upload.branch_id,
            DailyUpload.business_date == upload.business_date, DailyUpload.is_current.is_(True),
            DailyUpload.id != upload.id).with_for_update()).all()
        replaced_upload_ids = [prior.id for prior in old_current]
        replaced_upload_ids.append(upload.id)

        # Existing movement and coverage provenance stays attached to its
        # source version. This lifecycle does not synthesize either record.
        prior_purchase_lines = select(PurchaseLine.id).where(
            PurchaseLine.source_upload_id.in_([prior.id for prior in old_current]))
        db.execute(delete(PurchaseReceiptCurrentLine).where(
            PurchaseReceiptCurrentLine.purchase_line_id.in_(prior_purchase_lines)))

        granularity = result.metadata["source granularity"].upper()
        sales_by_ref: dict[str, SalesRecord] = {}
        for row in result.rows.get("Daily Sales", []):
            sku = str(row["SKU"]).strip()
            if granularity == "TRANSACTION":
                transaction_id, line_id = str(row["Transaction ID"]).strip(), str(row["Line ID"]).strip()
                source_identity = f"{transaction_id}:{line_id}"
                tx_at = row["Transaction DateTime"]
            else:
                aggregate_id = str(row["Aggregate ID"]).strip()
                source_identity = f"{aggregate_id}:{sku}"
                transaction_id = line_id = None
                tx_at = None
            record = SalesRecord(company_id=upload.company_id, branch_id=upload.branch_id,
                source_upload_id=upload.id, product_id=products[sku].id, business_date=upload.business_date,
                recipe_version_id=row.get("__recipe_version_id"),
                granularity=granularity, transaction_id=transaction_id, line_id=line_id,
                aggregate_id=str(row["Aggregate ID"]).strip() if granularity == "AGGREGATED" else None,
                source_identity=source_identity, transaction_at=tx_at, quantity=row["Quantity"],
                unit_price=row["Unit Selling Price"], discount_amount=row["Discount Amount"],
                tax_amount=row["Tax Amount"], net_amount=row["Net Amount"],
                sales_channel=row.get("Sales Channel"))
            db.add(record)
            if row.get("Sales Row Reference"):
                sales_by_ref[str(row["Sales Row Reference"]).strip()] = record
        db.flush()
        for row in result.rows.get("Sales Modifiers", []):
            sale = sales_by_ref.get(str(row.get("Sales Row Reference") or "").strip())
            option_id = row.get("__modifier_option_id")
            if sale is not None and option_id is not None:
                db.add(SalesRecordModifier(sales_record_id=sale.id, modifier_option_id=option_id,
                    selection_quantity=row.get("Selection Quantity")))
        inventory_by_sku_batch: dict[tuple[str, str], InventorySnapshot] = {}
        for row in result.rows.get("Inventory", []):
            sku = str(row["SKU"]).strip()
            snapshot = InventorySnapshot(company_id=upload.company_id, branch_id=upload.branch_id,
                source_upload_id=upload.id, product_id=products[sku].id, business_date=upload.business_date,
                batch_number=str(row.get("Batch Number") or "").strip(),
                opening_quantity=row["Opening Quantity"], closing_quantity=row["Closing Quantity"],
                unit=str(row["Unit"]).strip(), expiry_date=_as_date(row.get("Expiry Date")),
                unit_cost=row.get("Unit Cost"), damaged_quantity=row.get("Damaged Quantity") or Decimal(0),
                wasted_quantity=row.get("Wasted Quantity") or Decimal(0),
                staff_consumption_quantity=row.get("Staff Consumption Quantity"),
                adjustment_quantity=row.get("Adjustment Quantity") or Decimal(0),
                adjustment_reason=row.get("Adjustment Reason"))
            db.add(snapshot)
            inventory_by_sku_batch[(sku, snapshot.batch_number)] = snapshot
        if result.metadata.get("template version") == "3.0":
            db.flush()
        new_purchase_lines: list[PurchaseLine] = []
        for row in result.rows.get("Purchases", []):
            sku = str(row["SKU"]).strip()
            raw_identity_id = row.get("__receipt_identity_id")
            receipt_identity_id = UUID(str(raw_identity_id)) if raw_identity_id else None
            receipt_event_id = str(row.get("Receipt Event ID") or "").strip()
            if result.metadata.get("template version") == "3.0" and receipt_event_id:
                identity = db.scalar(select(PurchaseReceiptIdentity).where(
                    PurchaseReceiptIdentity.company_id == upload.company_id,
                    PurchaseReceiptIdentity.branch_id == upload.branch_id,
                    PurchaseReceiptIdentity.receipt_event_id == receipt_event_id,
                ))
                if identity is None:
                    identity = PurchaseReceiptIdentity(company_id=upload.company_id,
                        branch_id=upload.branch_id, receipt_event_id=receipt_event_id)
                    db.add(identity)
                    db.flush()
                receipt_identity_id = identity.id
            if receipt_identity_id is not None:
                identity = db.get(PurchaseReceiptIdentity, receipt_identity_id)
                if identity is None or identity.company_id != upload.company_id or identity.branch_id != upload.branch_id:
                    raise ValueError("Purchase receipt identity is not valid for this company and branch.")
            purchase_unit = row.get("Purchase Unit")
            batch_number = row.get("Batch Number")
            if result.metadata.get("template version") == "3.0":
                purchase_unit = products[sku].unit_of_measure
                batch_number = str(batch_number or "").strip() or None
            line = PurchaseLine(company_id=upload.company_id, branch_id=upload.branch_id,
                source_upload_id=upload.id, product_id=products[sku].id,
                receipt_id=str(row["Receipt ID"]).strip(), receipt_line_id=str(row["Receipt Line ID"]).strip(),
                business_date=upload.business_date, receipt_date=_as_date(row["Receipt Date"]),
                supplier_name=row.get("Supplier Name"),
                quantity_received=row["Quantity Received"], unit_purchase_price=row.get("Unit Purchase Price"),
                purchase_unit=purchase_unit, batch_number=batch_number,
                expiry_date=_as_date(row.get("Expiry Date")), receipt_identity_id=receipt_identity_id)
            db.add(line)
            if result.metadata.get("template version") == "3.0" and receipt_identity_id is not None:
                db.flush()
                db.add(StockMovement(company_id=upload.company_id, branch_id=upload.branch_id,
                    ingredient_product_id=products[sku].id, movement_date=line.receipt_date,
                    movement_type="PURCHASE_RECEIPT", quantity=line.quantity_received,
                    unit=products[sku].unit_of_measure, batch_number=line.batch_number,
                    source_upload_id=upload.id, purchase_line_id=line.id, transfer_id=None,
                    origin_type="UPLOAD", physical_event_id=receipt_identity_id,
                    source_reference=receipt_event_id, reason_code="RECEIVED_FROM_SUPPLIER",
                    reason_detail=None, created_by_user_id=None))
            new_purchase_lines.append(line)

        for row in result.rows.get("Stock Movements", []):
            sku = str(row["Ingredient SKU"]).strip()
            db.add(StockMovement(company_id=upload.company_id, branch_id=upload.branch_id,
                ingredient_product_id=products[sku].id,
                movement_date=_as_date(row["Movement Date"]),
                movement_type=str(row["Movement Type"]).strip().upper(),
                quantity=row["Quantity"], unit=str(row["Unit"]).strip(),
                batch_number=str(row.get("Batch Number") or "").strip() or None,
                source_upload_id=upload.id, purchase_line_id=None, transfer_id=None,
                origin_type="UPLOAD", physical_event_id=row["__physical_event_id"],
                source_reference=None,
                reason_code=str(row["Reason Code"]).strip(),
                reason_detail=row.get("Reason Detail"), created_by_user_id=None))

        if result.metadata.get("template version") == "3.0":
            db.flush()
            for row in result.rows.get("Stock Coverage", []):
                sku = str(row["Ingredient SKU"]).strip()
                batch = str(row.get("Batch Number") or "").strip()
                scope = str(row["Scope Type"]).strip().upper()
                snapshot = inventory_by_sku_batch.get((sku, batch)) if scope == "BATCH" else None
                db.add(StockCoverageDeclaration(company_id=upload.company_id,
                    branch_id=upload.branch_id, business_date=upload.business_date,
                    source_upload_id=upload.id, ingredient_product_id=products[sku].id,
                    unit=products[sku].unit_of_measure,
                    coverage_dimension=str(row["Coverage Dimension"]).strip().upper(),
                    scope_type=scope, batch_number=batch if scope == "BATCH" else None,
                    movement_type=(str(row.get("Movement Type") or "").strip().upper()
                        if str(row["Coverage Dimension"]).strip().upper() == "MOVEMENT_CATEGORY" else None),
                    status=str(row["Status"]).strip().upper(),
                    inventory_snapshot_id=snapshot.id if snapshot is not None else None))

        # Remove old-current pointers only after their replacement lines are
        # known to be valid. If an identity is still pointed at another version,
        # fail closed rather than detaching an unrelated current receipt.
        db.flush()
        for line in new_purchase_lines:
            if line.receipt_identity_id is None:
                continue
            existing = db.get(PurchaseReceiptCurrentLine, line.receipt_identity_id)
            if existing is not None:
                if existing.purchase_line_id not in {
                    row[0] for row in db.execute(select(PurchaseLine.id).where(
                        PurchaseLine.source_upload_id.in_(replaced_upload_ids)))
                }:
                    raise ValueError("Purchase receipt identity already has a current line outside the replaced upload versions.")
                db.delete(existing)
            db.add(PurchaseReceiptCurrentLine(receipt_identity_id=line.receipt_identity_id,
                company_id=upload.company_id, branch_id=upload.branch_id, purchase_line_id=line.id))

        for prior in old_current:
            prior.is_current = False
        # Release the partial unique key before promoting, within this transaction.
        db.flush()
        upload.is_current = True
        upload.processing_status = "COMPLETED"
        db.commit()
    except Exception:
        # A database error after inserts must leave the previous current upload,
        # receipt pointers, and all historical rows untouched.
        db.rollback()
        raise
    db.refresh(upload)
    return upload
