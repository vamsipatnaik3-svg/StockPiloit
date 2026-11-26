from pathlib import Path
from datetime import date, datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from app.services.workbook import HEADERS

OUT = Path(__file__).resolve().parents[1] / "templates" / "tavuno_standard_template_v1.xlsx"
OUT.parent.mkdir(parents=True, exist_ok=True)
wb = Workbook()
metadata = wb.active
metadata.title = "Metadata"
metadata.append(["Field", "Value"])
for row in [
    ("Template Version", "1.0"), ("Business Date", date(2026, 11, 25)),
    ("Branch Reference", "BR-001"), ("Currency", "INR"),
    ("Source System", "POS"), ("Prepared By", "Store Manager"),
    ("Source Granularity", "TRANSACTION"),
]:
    metadata.append(row)
metadata["B3"].number_format = "yyyy-mm-dd"
metadata["A10"] = "Instructions"
metadata["B10"] = "Keep the four required sheets and header names. Replace examples with your data. Required fields are marked in the headers. The backend recalculates net amounts."
metadata["B10"].alignment = Alignment(wrap_text=True, vertical="top")
metadata.row_dimensions[10].height = 45
granularity = DataValidation(type="list", formula1='"TRANSACTION,AGGREGATED"', allow_blank=False)
metadata.add_data_validation(granularity)
granularity.add(metadata["B8"])

for name in ("Daily Sales", "Inventory", "Purchases"):
    ws = wb.create_sheet(name)
    headers = list(HEADERS[name])
    ws.append([header + (" *" if header in {
        "Transaction ID", "Line ID", "Transaction DateTime", "SKU", "Quantity", "Unit Selling Price", "Discount Amount", "Tax Amount", "Net Amount",
        "Opening Quantity", "Closing Quantity", "Unit", "Receipt ID", "Receipt Line ID", "Receipt Date", "Quantity Received",
    } else " (optional)") for header in headers])
    if name == "Daily Sales":
        ws.append(["BILL-1001", "1", datetime(2026, 11, 25, 10, 15), "SKU-001", 2, 100, 10, 17.1, 207.1, "POS row 1001"])
        ws.append(["BILL-1001", "2", datetime(2026, 11, 25, 10, 15), "SKU-002", 1, 250, 0, 45, 295, "POS row 1001"])
    elif name == "Inventory":
        ws.append(["SKU-001", "LOT-01", 8, 16, "EA", None, 52.5, 0, 0, 0, None])
    else:
        ws.append(["GRN-1001", "1", date(2026, 11, 25), "Example Supplier", "SKU-001", 10, 52.5, "LOT-02", None])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{chr(64 + len(headers))}500"
    widths = [max(16, min(24, len(str(header)) + 4)) for header in headers]
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + index)].width = width
    if name == "Daily Sales":
        for row in range(2, 502):
            ws.cell(row, 3).number_format = "yyyy-mm-dd hh:mm:ss"
            for col in range(6, 10):
                ws.cell(row, col).number_format = '#,##0.00'
        positive = DataValidation(type="decimal", operator="greaterThan", formula1="0", allow_blank=True)
        ws.add_data_validation(positive)
        positive.add("E2:E500")
    if name == "Inventory":
        for row in range(2, 502):
            ws.cell(row, 6).number_format = "yyyy-mm-dd"
            ws.cell(row, 7).number_format = '#,##0.00'
    if name == "Purchases":
        for row in range(2, 502):
            ws.cell(row, 3).number_format = "yyyy-mm-dd"
            ws.cell(row, 7).number_format = '#,##0.00'

for ws in wb.worksheets:
    ws.freeze_panes = ws.freeze_panes or "A2"
    for cell in ws[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor="17365D")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[1].height = 34
    ws.sheet_view.showGridLines = False

wb.save(OUT)
print(OUT)
