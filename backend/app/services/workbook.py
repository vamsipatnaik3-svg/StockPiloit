from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
import re

from openpyxl import load_workbook

TEMPLATE_VERSION = "1.0"  # Retained for callers and the shipped v1 template.
CAFE_TEMPLATE_VERSION = "2.0"
STOCK_TEMPLATE_VERSION = "3.0"
SHEETS = ("Metadata", "Daily Sales", "Inventory", "Purchases")
CAFE_SHEETS = (*SHEETS, "Sales Modifiers")
V3_SHEETS = (*CAFE_SHEETS, "Stock Movements", "Stock Coverage")
HEADERS = {
    "Metadata": ("Field", "Value"),
    "Daily Sales": ("Transaction ID", "Line ID", "Transaction DateTime", "SKU", "Quantity", "Unit Selling Price", "Discount Amount", "Tax Amount", "Net Amount", "Source Reference", "Aggregate ID"),
    "Inventory": ("SKU", "Batch Number", "Opening Quantity", "Closing Quantity", "Unit", "Expiry Date", "Unit Cost", "Damaged Quantity", "Wasted Quantity", "Adjustment Quantity", "Adjustment Reason"),
    "Purchases": ("Receipt ID", "Receipt Line ID", "Receipt Date", "Supplier Name", "SKU", "Quantity Received", "Unit Purchase Price", "Batch Number", "Expiry Date"),
}
CAFE_HEADERS = {
    **HEADERS,
    "Daily Sales": (*HEADERS["Daily Sales"], "Sales Row Reference", "Sales Channel"),
    "Inventory": (*HEADERS["Inventory"], "Staff Consumption Quantity"),
    "Purchases": (*HEADERS["Purchases"], "Purchase Unit"),
    "Sales Modifiers": ("Sales Row Reference", "Modifier Group", "Modifier Option", "Selection Quantity"),
}
V3_HEADERS = {
    **CAFE_HEADERS,
    "Purchases": (*CAFE_HEADERS["Purchases"], "Receipt Event ID"),
    "Stock Movements": (
        "Physical Event ID", "Movement Date", "Ingredient SKU", "Movement Type",
        "Quantity", "Unit", "Batch Number", "Reason Code", "Reason Detail",
    ),
    "Stock Coverage": (
        "Ingredient SKU", "Coverage Dimension", "Scope Type", "Batch Number",
        "Movement Type", "Status", "Unit",
    ),
}
REQUIRED_COLUMNS = {
    "Daily Sales": HEADERS["Daily Sales"][:9],
    "Inventory": ("SKU", "Opening Quantity", "Closing Quantity", "Unit"),
    "Purchases": ("Receipt ID", "Receipt Line ID", "Receipt Date", "SKU", "Quantity Received"),
}


@dataclass
class WorkbookIssue:
    severity: str
    sheet: str
    row: int | None
    code: str
    message: str


@dataclass
class ParsedWorkbook:
    metadata: dict[str, object] = field(default_factory=dict)
    rows: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    issues: list[WorkbookIssue] = field(default_factory=list)


def _header(value: object) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "").strip()).casefold()
    return re.sub(r"\s+(\*|\(optional\))$", "", normalized)


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def normalize_date(value: object) -> date | None:
    """Normalize date-like workbook/API values without timezone shifting date-only data."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(raw, "%d/%m/%Y").date()
    except ValueError:
        return None


def _decimal(value: object, sheet: str, row: int, column: str, result: ParsedWorkbook) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        # Convert through string to avoid binary float arithmetic in calculations.
        parsed = Decimal(str(value))
        if not parsed.is_finite():
            raise InvalidOperation
        return parsed
    except (InvalidOperation, ValueError):
        result.issues.append(WorkbookIssue("ERROR", sheet, row, "INVALID_NUMBER", f"{column} must be a valid number."))
        return None


def read_workbook(content: bytes) -> ParsedWorkbook:
    result = ParsedWorkbook()
    try:
        workbook = load_workbook(BytesIO(content), data_only=True, read_only=True)
    except Exception:
        result.issues.append(WorkbookIssue("ERROR", "", None, "CORRUPTED_WORKBOOK", "The file is not a readable .xlsx workbook."))
        return result
    if "Metadata" in workbook.sheetnames:
        metadata_sheet = workbook["Metadata"]
        for row in metadata_sheet.iter_rows(min_row=2, values_only=True):
            key = _text(row[0] if row else "")
            value = row[1] if len(row) > 1 else None
            if key and value is not None:
                normalized_key = key.casefold()
                if normalized_key == "business date":
                    normalized_date = normalize_date(value)
                    result.metadata[normalized_key] = normalized_date if normalized_date is not None else _text(value)
                elif isinstance(value, (date, datetime)):
                    result.metadata[normalized_key] = value.isoformat()
                else:
                    result.metadata[normalized_key] = _text(value)
    version = result.metadata.get("template version", "")
    supported_versions = {TEMPLATE_VERSION, CAFE_TEMPLATE_VERSION, STOCK_TEMPLATE_VERSION}
    if version not in supported_versions:
        result.issues.append(WorkbookIssue("ERROR", "Metadata", None, "UNSUPPORTED_TEMPLATE_VERSION", f"Template version {version or '(missing)'} is not supported; expected 1.0, 2.0 or 3.0."))
    is_v3 = version == STOCK_TEMPLATE_VERSION
    is_cafe = version in {CAFE_TEMPLATE_VERSION, STOCK_TEMPLATE_VERSION}
    sheets = V3_SHEETS if is_v3 else (CAFE_SHEETS if is_cafe else SHEETS)
    headers = V3_HEADERS if is_v3 else (CAFE_HEADERS if is_cafe else HEADERS)
    for name in sheets:
        if name not in workbook.sheetnames:
            result.issues.append(WorkbookIssue("ERROR", name, None, "MISSING_SHEET", f"Required sheet '{name}' is missing."))
    if result.metadata.get("source granularity", "").upper() not in {"TRANSACTION", "AGGREGATED"}:
        result.issues.append(WorkbookIssue("ERROR", "Metadata", None, "INVALID_GRANULARITY", "Source Granularity must be TRANSACTION or AGGREGATED."))
    for field_name in ("business date", "branch reference", "currency"):
        if not result.metadata.get(field_name):
            result.issues.append(WorkbookIssue("ERROR", "Metadata", None, "MISSING_METADATA", f"Metadata field '{field_name}' is required."))

    seen_sales: set[tuple[str, str]] = set()
    seen_aggregates: set[tuple[str, str]] = set()
    seen_inventory_batches: set[tuple[str, str]] = set()
    seen_receipt_events: set[str] = set()
    if is_cafe:
        result.rows["Sales Modifiers"] = []
    for sheet_name in sheets[1:]:
        if sheet_name not in workbook.sheetnames:
            result.rows[sheet_name] = []
            continue
        sheet = workbook[sheet_name]
        first = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
        header_map = {_header(value): index for index, value in enumerate(first) if value is not None}
        required_columns = REQUIRED_COLUMNS.get(sheet_name, ())
        if is_cafe and not is_v3:
            required_columns = {
                "Daily Sales": (*REQUIRED_COLUMNS["Daily Sales"], "Sales Row Reference", "Sales Channel"),
                "Inventory": (*REQUIRED_COLUMNS["Inventory"],),
                "Purchases": (*REQUIRED_COLUMNS["Purchases"], "Purchase Unit"),
                "Sales Modifiers": ("Sales Row Reference", "Modifier Group", "Modifier Option", "Selection Quantity"),
            }[sheet_name]
        if is_v3:
            required_columns = {
                "Daily Sales": (*REQUIRED_COLUMNS["Daily Sales"], "Sales Row Reference", "Sales Channel"),
                "Inventory": REQUIRED_COLUMNS["Inventory"],
                "Purchases": (*REQUIRED_COLUMNS["Purchases"], "Purchase Unit", "Receipt Event ID"),
                "Sales Modifiers": ("Sales Row Reference", "Modifier Group", "Modifier Option", "Selection Quantity"),
                "Stock Movements": ("Physical Event ID", "Movement Date", "Ingredient SKU", "Movement Type", "Quantity", "Unit", "Reason Code"),
                "Stock Coverage": ("Ingredient SKU", "Coverage Dimension", "Scope Type", "Status", "Unit"),
            }[sheet_name]
        if sheet_name == "Daily Sales" and result.metadata.get("source granularity", "").upper() == "AGGREGATED":
            required_columns = ("SKU", "Quantity", "Unit Selling Price", "Discount Amount", "Tax Amount", "Net Amount")
        if is_cafe and sheet_name == "Daily Sales":
            required_columns = (*required_columns, "Sales Row Reference", "Sales Channel")
        missing_headers = [name for name in required_columns if _header(name) not in header_map]
        for name in missing_headers:
            result.issues.append(WorkbookIssue("ERROR", sheet_name, 1, "MISSING_COLUMN", f"Required column '{name}' is missing."))
        if missing_headers:
            result.rows[sheet_name] = []
            continue
        rows = []
        for row_number, values in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            if not any(value is not None for value in values):
                continue
            item = {name: (values[header_map[_header(name)]] if header_map.get(_header(name), 10**6) < len(values) else None) for name in headers[sheet_name]}
            if sheet_name == "Sales Modifiers":
                item["Selection Quantity"] = _decimal(item["Selection Quantity"], sheet_name, row_number, "Selection Quantity", result)
                if not all(_text(item.get(key)) for key in ("Sales Row Reference", "Modifier Group", "Modifier Option")):
                    result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number, "MISSING_MODIFIER_FIELDS", "Sales Row Reference, Modifier Group and Modifier Option are required."))
                if item["Selection Quantity"] is None or item["Selection Quantity"] <= 0:
                    result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number, "INVALID_SELECTION_QUANTITY", "Selection Quantity must be greater than zero."))
                rows.append(item)
                continue
            if sheet_name == "Stock Movements":
                for column in ("Physical Event ID", "Ingredient SKU", "Movement Type", "Unit", "Reason Code"):
                    item[column] = _text(item.get(column))
                item["Batch Number"] = _text(item.get("Batch Number")) or None
                item["Reason Detail"] = _text(item.get("Reason Detail")) or None
                if not all(item.get(column) for column in (
                    "Physical Event ID", "Ingredient SKU", "Movement Type", "Unit", "Reason Code")):
                    result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number,
                        "MISSING_MOVEMENT_FIELDS", "Physical Event ID, Ingredient SKU, Movement Type, Unit and Reason Code are required."))
                movement_date = normalize_date(item.get("Movement Date"))
                if movement_date is None:
                    result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number,
                        "INVALID_MOVEMENT_DATE", "Movement Date must be a valid date."))
                item["Movement Date"] = movement_date
                item["Quantity"] = _decimal(item.get("Quantity"), sheet_name, row_number, "Quantity", result)
                if item["Quantity"] is None:
                    result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number,
                        "MISSING_MOVEMENT_QUANTITY", "Quantity is required."))
                rows.append(item)
                continue
            if sheet_name == "Stock Coverage":
                for column in ("Ingredient SKU", "Coverage Dimension", "Scope Type", "Movement Type", "Status", "Unit"):
                    item[column] = _text(item.get(column))
                item["Batch Number"] = _text(item.get("Batch Number")) or None
                if not all(item.get(column) for column in (
                    "Ingredient SKU", "Coverage Dimension", "Scope Type", "Status", "Unit")):
                    result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number,
                        "MISSING_COVERAGE_FIELDS", "Ingredient SKU, Coverage Dimension, Scope Type, Status and Unit are required."))
                rows.append(item)
                continue
            if sheet_name == "Daily Sales":
                if is_cafe and (not _text(item.get("Sales Row Reference")) or not _text(item.get("Sales Channel"))):
                    result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number, "MISSING_CAFE_SALES_FIELDS", "Sales Row Reference and Sales Channel are required in template 2.0."))
                for col in ("Quantity", "Unit Selling Price", "Discount Amount", "Tax Amount", "Net Amount"):
                    item[col] = _decimal(item[col], sheet_name, row_number, col, result)
                    if item[col] is None:
                        result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number, "MISSING_SALES_VALUE", f"{col} is required."))
                quantity, price = item["Quantity"], item["Unit Selling Price"]
                discount, tax, net = item["Discount Amount"], item["Tax Amount"], item["Net Amount"]
                if all(isinstance(x, Decimal) for x in (quantity, price, discount, tax, net)):
                    if quantity <= 0 or price < 0 or discount < 0 or tax < 0:
                        result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number, "INVALID_SALES_AMOUNT", "Quantity must be positive; price, discount and tax cannot be negative."))
                    elif (quantity * price - discount + tax).quantize(Decimal("0.01")) != net.quantize(Decimal("0.01")):
                        result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number, "NET_AMOUNT_MISMATCH", "Net Amount does not equal quantity × price − discount + tax."))
                granularity = result.metadata.get("source granularity", "").upper()
                if granularity == "TRANSACTION":
                    identity = (_text(item["Transaction ID"]), _text(item["Line ID"]))
                    if not all(identity) or not _text(item["SKU"]):
                        result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number, "MISSING_SALES_IDENTITY", "Transaction ID, Line ID and SKU are required."))
                    elif identity in seen_sales:
                        result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number, "DUPLICATE_SALES_LINE", "Transaction ID and Line ID are duplicated in this workbook."))
                    seen_sales.add(identity)
                elif granularity == "AGGREGATED":
                    aggregate_identity = (_text(item["Aggregate ID"]), _text(item["SKU"]))
                    if not all(aggregate_identity):
                        result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number, "MISSING_AGGREGATE_IDENTITY", "Aggregate ID and SKU are required for aggregate sales."))
                    elif aggregate_identity in seen_aggregates:
                        result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number, "DUPLICATE_AGGREGATE_LINE", "Aggregate ID and SKU are duplicated in this workbook."))
                    seen_aggregates.add(aggregate_identity)
                tx_date = item.get("Transaction DateTime")
                if granularity == "TRANSACTION" and not isinstance(tx_date, datetime):
                    try:
                        item["Transaction DateTime"] = datetime.fromisoformat(_text(tx_date))
                    except ValueError:
                        result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number, "INVALID_TRANSACTION_DATETIME", "Transaction DateTime must contain a valid date and time."))
            if sheet_name == "Inventory":
                if not _text(item["SKU"]) or not _text(item["Unit"]):
                    result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number, "MISSING_INVENTORY_FIELDS", "SKU and Unit are required."))
                inventory_identity = (_text(item["SKU"]), _text(item["Batch Number"]))
                if inventory_identity in seen_inventory_batches:
                    result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number, "DUPLICATE_INVENTORY_BATCH", "SKU and Batch Number are duplicated in this workbook."))
                seen_inventory_batches.add(inventory_identity)
                for col in ("Opening Quantity", "Closing Quantity", "Damaged Quantity", "Wasted Quantity", "Adjustment Quantity", "Unit Cost", "Staff Consumption Quantity"):
                    item[col] = _decimal(item.get(col), sheet_name, row_number, col, result)
                for col in ("Opening Quantity", "Closing Quantity"):
                    if item[col] is None:
                        result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number, "MISSING_INVENTORY_VALUE", f"{col} is required."))
            if sheet_name == "Purchases":
                if is_cafe and not _text(item.get("Purchase Unit")):
                    result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number, "MISSING_PURCHASE_UNIT", "Purchase Unit is required in template 2.0."))
                if not all(_text(item[x]) for x in ("Receipt ID", "Receipt Line ID", "SKU")):
                    result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number, "MISSING_PURCHASE_IDENTITY", "Receipt ID, Receipt Line ID and SKU are required."))
                if is_v3:
                    event_id = _text(item.get("Receipt Event ID"))
                    item["Receipt Event ID"] = event_id
                    if not event_id:
                        result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number,
                            "MISSING_RECEIPT_EVENT_ID", "Receipt Event ID is required in template 3.0."))
                    elif len(event_id) > 150:
                        result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number,
                            "INVALID_RECEIPT_EVENT_ID", "Receipt Event ID cannot exceed 150 characters."))
                    elif event_id in seen_receipt_events:
                        result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number,
                            "DUPLICATE_RECEIPT_EVENT_ID", "Receipt Event ID must identify one physical receipt event per workbook."))
                    seen_receipt_events.add(event_id)
                item["Quantity Received"] = _decimal(item["Quantity Received"], sheet_name, row_number, "Quantity Received", result)
                item["Unit Purchase Price"] = _decimal(item["Unit Purchase Price"], sheet_name, row_number, "Unit Purchase Price", result)
                if item["Quantity Received"] is None:
                    result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number, "MISSING_PURCHASE_QUANTITY", "Quantity Received is required."))
                receipt_date = item["Receipt Date"]
                if not isinstance(receipt_date, (date, datetime)):
                    try:
                        item["Receipt Date"] = date.fromisoformat(_text(receipt_date))
                    except ValueError:
                        result.issues.append(WorkbookIssue("ERROR", sheet_name, row_number, "INVALID_RECEIPT_DATE", "Receipt Date must be a valid date."))
            rows.append(item)
        result.rows[sheet_name] = rows
    workbook.close()
    return result
