from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from app.services.workbook import CAFE_HEADERS


OUT = Path(__file__).resolve().parents[1] / "templates" / "tavuno_cafe_template_v2.xlsx"
OUT.parent.mkdir(parents=True, exist_ok=True)
wb = Workbook()
metadata = wb.active
metadata.title = "Metadata"
metadata.append(["Field", "Value"])
for row in [
    ("Template Version", "2.0"), ("Business Date", date(2026, 11, 25)),
    ("Branch Reference", "BR-001"), ("Currency", "INR"),
    ("Source Granularity", "AGGREGATED"),
]:
    metadata.append(row)
metadata["B3"].number_format = "yyyy-mm-dd"
metadata.append(["Instructions", "Use a unique Sales Row Reference for every Daily Sales row. Sales Modifiers can contain multiple options for that reference; Selection Quantity is the number of sold units selecting the option. Use canonical ingredient units exactly; no conversion is performed."])
metadata["B7"].alignment = Alignment(wrap_text=True, vertical="top")
metadata.row_dimensions[7].height = 55
granularity = DataValidation(type="list", formula1='"TRANSACTION,AGGREGATED"', allow_blank=False)
metadata.add_data_validation(granularity)
granularity.add(metadata["B6"])

for name in CAFE_HEADERS:
    if name == "Metadata":
        continue
    ws = wb.create_sheet(name)
    ws.append(list(CAFE_HEADERS[name]))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{chr(64 + len(CAFE_HEADERS[name]))}500"
    for index, header in enumerate(CAFE_HEADERS[name], start=1):
        ws.column_dimensions[chr(64 + index)].width = max(16, min(28, len(header) + 4))
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
