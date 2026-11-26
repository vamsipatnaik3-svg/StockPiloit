from io import BytesIO
from pathlib import Path
from datetime import date, datetime

from openpyxl import Workbook, load_workbook

from app.services.workbook import V3_HEADERS, read_workbook


def make_workbook(net=207.1, include_inventory=True, granularity="TRANSACTION", metadata_date="2026-11-25"):
    wb = Workbook()
    meta = wb.active
    meta.title = "Metadata"
    for row in [("Field", "Value"), ("Template Version", "1.0"), ("Business Date", metadata_date),
                ("Branch Reference", "BR-001"), ("Currency", "INR"), ("Source Granularity", granularity)]:
        meta.append(row)
    sales = wb.create_sheet("Daily Sales")
    sales.append(["Transaction ID", "Line ID", "Transaction DateTime", "SKU", "Quantity", "Unit Selling Price", "Discount Amount", "Tax Amount", "Net Amount", "Source Reference", "Aggregate ID"])
    sales.append(["BILL-1" if granularity == "TRANSACTION" else None, "1" if granularity == "TRANSACTION" else None,
                  "2026-11-25 10:00" if granularity == "TRANSACTION" else None, "SKU-1", 2, 100, 10, 17.1, net,
                  None, "POS-DAY-001" if granularity == "AGGREGATED" else None])
    if include_inventory:
        wb.create_sheet("Inventory").append(["SKU", "Opening Quantity", "Closing Quantity", "Unit"])
    wb.create_sheet("Purchases").append(["Receipt ID", "Receipt Line ID", "Receipt Date", "SKU", "Quantity Received"])
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def test_reads_valid_workbook_and_recalculates_money():
    result = read_workbook(make_workbook())
    assert not [issue for issue in result.issues if issue.severity == "ERROR"]
    assert result.metadata["source granularity"] == "TRANSACTION"
    assert len(result.rows["Daily Sales"]) == 1


def test_reports_wrong_net_amount_and_missing_sheet():
    result = read_workbook(make_workbook(net=200, include_inventory=False))
    codes = {issue.code for issue in result.issues}
    assert "NET_AMOUNT_MISMATCH" in codes
    assert "MISSING_SHEET" in codes


def test_aggregated_sales_keeps_aggregate_identity_without_transaction_ids():
    result = read_workbook(make_workbook(granularity="AGGREGATED"))
    assert not [issue for issue in result.issues if issue.severity == "ERROR"]
    row = result.rows["Daily Sales"][0]
    assert row["Aggregate ID"] == "POS-DAY-001"
    assert row["Transaction ID"] is None


def test_business_date_normalizes_excel_datetime_date_and_string_representations():
    expected = date(2026, 11, 25)
    for value in (
        datetime(2026, 11, 25, 0, 0),
        expected,
        "2026-11-25",
        "25/11/2026",
        "2026-11-25T00:00:00",
    ):
        result = read_workbook(make_workbook(metadata_date=value))
        assert result.metadata["business date"] == expected
        assert not any(issue.code == "MISSING_METADATA" for issue in result.issues)


def test_corrupt_workbook_is_reported():
    result = read_workbook(b"not an excel workbook")
    assert result.issues[0].code == "CORRUPTED_WORKBOOK"


def test_shipped_standard_template_is_readable():
    path = Path(__file__).resolve().parents[1] / "templates" / "tavuno_standard_template_v1.xlsx"
    result = read_workbook(path.read_bytes())
    assert not [issue for issue in result.issues if issue.severity == "ERROR"]
    assert set(result.rows) == {"Daily Sales", "Inventory", "Purchases"}


def test_shipped_cafe_template_has_five_sheets_and_v2_fields():
    path = Path(__file__).resolve().parents[1] / "templates" / "tavuno_cafe_template_v2.xlsx"
    result = read_workbook(path.read_bytes())
    assert not [issue for issue in result.issues if issue.severity == "ERROR"]
    assert set(result.rows) == {"Daily Sales", "Inventory", "Purchases", "Sales Modifiers"}
    assert result.metadata["template version"] == "2.0"


def test_shipped_cafe_v3_template_has_required_v3_sheets_and_fields():
    path = Path(__file__).resolve().parents[1] / "templates" / "tavuno_cafe_template_v3.xlsx"
    result = read_workbook(path.read_bytes())
    assert not [issue for issue in result.issues if issue.severity == "ERROR"]
    assert set(result.rows) == {"Daily Sales", "Inventory", "Purchases", "Sales Modifiers",
        "Stock Movements", "Stock Coverage"}
    assert result.metadata["template version"] == "3.0"
    assert "Receipt Event ID" in V3_HEADERS["Purchases"]
    assert len(result.rows["Stock Movements"]) == 0


def test_v3_parser_detects_movement_quantity_and_missing_receipt_event_errors():
    wb = Workbook()
    metadata = wb.active
    metadata.title = "Metadata"
    for row in [("Field", "Value"), ("Template Version", "3.0"),
        ("Business Date", "2026-11-25"), ("Branch Reference", "BR-001"),
        ("Currency", "INR"), ("Source Granularity", "AGGREGATED")]:
        metadata.append(row)
    for name, columns in V3_HEADERS.items():
        if name != "Metadata":
            wb.create_sheet(name).append(list(columns))
    purchases = wb["Purchases"]
    purchases.append(["GRN-1", "LINE-1", "2026-11-25", "Supplier", "ING-1", 2, 10,
        "LOT-1", None, "g", None])
    movements = wb["Stock Movements"]
    movements.append(["invalid-uuid", "bad-date", "ING-1", "PURCHASE_RECEIPT", 0,
        "g", "LOT-1", "RECEIVED_FROM_SUPPLIER", None])
    output = BytesIO()
    wb.save(output)

    result = read_workbook(output.getvalue())
    codes = {issue.code for issue in result.issues}
    assert "MISSING_RECEIPT_EVENT_ID" in codes
    assert "INVALID_MOVEMENT_DATE" in codes
    assert "INVALID_NUMBER" not in codes
    assert result.rows["Stock Movements"][0]["Quantity"] == 0


def test_unsupported_template_version_is_reported_explicitly():
    wb = load_workbook(BytesIO(make_workbook()))
    wb["Metadata"]["B2"] = "4.0"
    output = BytesIO()
    wb.save(output)
    result = read_workbook(output.getvalue())
    issue = next(issue for issue in result.issues if issue.code == "UNSUPPORTED_TEMPLATE_VERSION")
    assert "1.0, 2.0 or 3.0" in issue.message
