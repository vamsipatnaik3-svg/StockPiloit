from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from app.services.workbook import V3_HEADERS


OUT = Path(__file__).resolve().parents[1] / "templates" / "tavuno_cafe_template_v3.xlsx"
OUT.parent.mkdir(parents=True, exist_ok=True)
wb = Workbook()
metadata = wb.active
metadata.title = "Metadata"
metadata.append(["Field", "Value"])
for row in [
    ("Template Version", "3.0"), ("Business Date", date(2026, 11, 25)),
    ("Branch Reference", "BR-001"), ("Currency", "INR"),
    ("Source Granularity", "AGGREGATED"),
]:
    metadata.append(row)
metadata["B3"].number_format = "yyyy-mm-dd"
metadata.append(["Instructions", "Version 3.0 adds stable Receipt Event IDs, non-purchase stock movements and explicit stock coverage. Use a stable UUID Physical Event ID across corrections. Use one Receipt Event ID per physical delivery line; separate partial deliveries need separate IDs. Use canonical ingredient units exactly; no conversion is performed. Movement dates must match the workbook Business Date. Do not enter purchase receipts or transfers on Stock Movements."])
metadata["B7"].alignment = Alignment(wrap_text=True, vertical="top")
metadata.row_dimensions[7].height = 82
granularity = DataValidation(type="list", formula1='"TRANSACTION,AGGREGATED"', allow_blank=False)
metadata.add_data_validation(granularity)
granularity.add(metadata["B6"])

for name, columns in V3_HEADERS.items():
    if name == "Metadata":
        continue
    ws = wb.create_sheet(name)
    ws.append(list(columns))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{ws.cell(row=1, column=len(columns)).column_letter}500"
    for index, header in enumerate(columns, start=1):
        ws.column_dimensions[ws.cell(row=1, column=index).column_letter].width = max(16, min(32, len(header) + 4))
    if name == "Daily Sales":
        for row in range(2, 502):
            ws.cell(row, 3).number_format = "yyyy-mm-dd hh:mm:ss"
            for column in range(6, 10):
                ws.cell(row, column).number_format = "#,##0.00"
    if name == "Inventory":
        for row in range(2, 502):
            ws.cell(row, 6).number_format = "yyyy-mm-dd"
    if name == "Purchases":
        for row in range(2, 502):
            ws.cell(row, 3).number_format = "yyyy-mm-dd"
            ws.cell(row, 9).number_format = "yyyy-mm-dd"
    if name == "Stock Movements":
        ws.column_dimensions["A"].width = 38
        for row in range(2, 502):
            ws.cell(row, 2).number_format = "yyyy-mm-dd"
        types = DataValidation(type="list", formula1='"OTHER_INFLOW,POSITIVE_ADJUSTMENT,WASTE,STAFF_CONSUMPTION,DAMAGE,NEGATIVE_ADJUSTMENT,OTHER_OUTFLOW"', allow_blank=False)
        ws.add_data_validation(types)
        types.add("D2:D501")
    if name == "Stock Coverage":
        dims = DataValidation(type="list", formula1='"INGREDIENT,BATCH,OPENING_STOCK,CLOSING_STOCK,MOVEMENT_CATEGORY"', allow_blank=False)
        scopes = DataValidation(type="list", formula1='"INGREDIENT,ALL_BATCHES,BATCH"', allow_blank=False)
        statuses = DataValidation(type="list", formula1='"COMPLETE,PARTIAL,UNREPORTED,NOT_APPLICABLE,NO_STOCK"', allow_blank=False)
        movement_types = DataValidation(type="list", formula1='"PURCHASE_RECEIPT,OTHER_INFLOW,POSITIVE_ADJUSTMENT,TRANSFER_IN,WASTE,STAFF_CONSUMPTION,DAMAGE,NEGATIVE_ADJUSTMENT,OTHER_OUTFLOW,TRANSFER_OUT"', allow_blank=True)
        for validation in (dims, scopes, statuses, movement_types):
            ws.add_data_validation(validation)
        dims.add("B2:B501")
        scopes.add("C2:C501")
        movement_types.add("E2:E501")
        statuses.add("F2:F501")

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
