from datetime import date
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.branch_scope import BranchAccessScope
from app.models import (Branch, DailyUpload, InventorySnapshot, Product,
    PurchaseLine, PurchaseReceiptCurrentLine, StockCoverageDeclaration,
    StockMovement, StockTransfer)
from app.services.theoretical_consumption_queries import load_theoretical_inputs


def load_actual_consumption_inputs(db: Session, company_id: UUID, start_date: date,
        end_date: date, branch_scope: BranchAccessScope,
        ingredient_id: UUID | None) -> dict:
    """Load tenant-scoped actual stock evidence and Phase 4B comparison inputs.

    Upload rows are retained historically, so every upload-origin fact is joined
    to the exact completed/current upload version before it reaches the calculator.
    Manual movements have no upload and are included only while not voided by the
    calculation layer.
    """
    if branch_scope.company_id != company_id or (
            not branch_scope.branch_ids and not (
                branch_scope.role == "OWNER" and branch_scope.scope_type == "COMPANY")):
        raise ValueError("Actual consumption requires a matching authorized branch scope.")
    branch_query = select(Branch).where(
        *branch_scope.criteria(Branch.company_id, Branch.id))
    branches = tuple(db.scalars(branch_query.order_by(Branch.name, Branch.id)).all())
    branch_ids = [branch.id for branch in branches]

    product_query = select(Product).where(
        Product.company_id == company_id,
        Product.product_kind == "INGREDIENT",
    )
    if ingredient_id is not None:
        product_query = product_query.where(Product.id == ingredient_id)
    products = tuple(db.scalars(product_query.order_by(Product.sku, Product.id)).all())
    product_ids = [product.id for product in products]

    if not branch_ids or not product_ids:
        scopes, sales = load_theoretical_inputs(db, company_id, start_date,
            end_date, branch_scope)
        return {"branches": branches, "products": products, "uploads": (),
            "snapshots": (), "declarations": (), "purchase_lines": (),
            "receipt_current_lines": (), "movements": (), "transfers": (), "theoretical_scopes": scopes,
            "theoretical_sales": sales}

    completed_uploads = tuple(db.scalars(select(DailyUpload).where(
        DailyUpload.company_id == company_id,
        DailyUpload.branch_id.in_(branch_ids),
        DailyUpload.is_current.is_(True),
        DailyUpload.processing_status == "COMPLETED",
    ).order_by(DailyUpload.business_date, DailyUpload.branch_id,
        DailyUpload.version)).all())
    current_upload_ids = {upload.id for upload in completed_uploads}
    period_uploads = tuple(upload for upload in completed_uploads
        if start_date <= upload.business_date <= end_date)

    snapshots: tuple[InventorySnapshot, ...] = ()
    if current_upload_ids:
        snapshots = tuple(db.scalars(select(InventorySnapshot).where(
            InventorySnapshot.company_id == company_id,
            InventorySnapshot.branch_id.in_(branch_ids),
            InventorySnapshot.product_id.in_(product_ids),
            InventorySnapshot.source_upload_id.in_(current_upload_ids),
            InventorySnapshot.business_date >= start_date,
            InventorySnapshot.business_date <= end_date,
        ).order_by(InventorySnapshot.business_date, InventorySnapshot.branch_id,
            InventorySnapshot.product_id, InventorySnapshot.batch_number)).all())

    purchase_lines: tuple[PurchaseLine, ...] = ()
    if current_upload_ids:
        purchase_lines = tuple(db.scalars(select(PurchaseLine).join(
            DailyUpload, DailyUpload.id == PurchaseLine.source_upload_id,
        ).where(
            PurchaseLine.company_id == company_id,
            PurchaseLine.branch_id.in_(branch_ids),
            PurchaseLine.product_id.in_(product_ids),
            PurchaseLine.receipt_date >= start_date,
            PurchaseLine.receipt_date <= end_date,
            DailyUpload.company_id == company_id,
            DailyUpload.branch_id == PurchaseLine.branch_id,
            DailyUpload.id.in_(current_upload_ids),
            DailyUpload.is_current.is_(True),
            DailyUpload.processing_status == "COMPLETED",
        ).order_by(PurchaseLine.receipt_date, PurchaseLine.branch_id,
            PurchaseLine.product_id, PurchaseLine.id)).all())
    receipt_identity_ids = {line.receipt_identity_id for line in purchase_lines
        if line.receipt_identity_id is not None}
    receipt_current_lines: tuple[PurchaseReceiptCurrentLine, ...] = ()
    if receipt_identity_ids:
        receipt_current_lines = tuple(db.scalars(select(PurchaseReceiptCurrentLine).where(
            PurchaseReceiptCurrentLine.company_id == company_id,
            PurchaseReceiptCurrentLine.branch_id.in_(branch_ids),
            PurchaseReceiptCurrentLine.receipt_identity_id.in_(receipt_identity_ids),
        )).all())

    # Include current upload versions that supplied in-period physical receipts,
    # even when their workbook business date is outside the receipt date range.
    declaration_upload_ids = set(upload.id for upload in period_uploads)
    declaration_upload_ids.update(line.source_upload_id for line in purchase_lines)
    declarations: tuple[StockCoverageDeclaration, ...] = ()
    if declaration_upload_ids and product_ids:
        declarations = tuple(db.scalars(select(StockCoverageDeclaration).where(
            StockCoverageDeclaration.company_id == company_id,
            StockCoverageDeclaration.branch_id.in_(branch_ids),
            StockCoverageDeclaration.ingredient_product_id.in_(product_ids),
            StockCoverageDeclaration.source_upload_id.in_(declaration_upload_ids),
        ).order_by(StockCoverageDeclaration.business_date,
            StockCoverageDeclaration.branch_id,
            StockCoverageDeclaration.ingredient_product_id)).all())

    scoped_transfer_ids = select(StockTransfer.id).where(
        StockTransfer.company_id == company_id,
        StockTransfer.ingredient_product_id.in_(product_ids),
        StockTransfer.movement_date >= start_date,
        StockTransfer.movement_date <= end_date,
        or_(StockTransfer.source_branch_id.in_(branch_ids),
            StockTransfer.destination_branch_id.in_(branch_ids)),
    )
    movement_query = select(StockMovement).where(
        StockMovement.company_id == company_id,
        StockMovement.ingredient_product_id.in_(product_ids),
        StockMovement.movement_date >= start_date,
        StockMovement.movement_date <= end_date,
        or_(StockMovement.branch_id.in_(branch_ids),
            StockMovement.transfer_id.in_(scoped_transfer_ids)),
        or_(
            (StockMovement.origin_type == "MANUAL") & StockMovement.source_upload_id.is_(None),
            StockMovement.source_upload_id.in_(current_upload_ids)
            if current_upload_ids else False,
        ),
    )
    # Load both transfer legs across the company so a branch-filtered result can
    # validate its counterpart and company totals can net transfers correctly.
    movements = tuple(db.scalars(movement_query.order_by(
        StockMovement.movement_date, StockMovement.ingredient_product_id,
        StockMovement.id)).all())

    transfer_query = select(StockTransfer).where(
        StockTransfer.company_id == company_id,
        StockTransfer.ingredient_product_id.in_(product_ids),
        StockTransfer.movement_date >= start_date,
        StockTransfer.movement_date <= end_date,
        or_(StockTransfer.source_branch_id.in_(branch_ids),
            StockTransfer.destination_branch_id.in_(branch_ids)),
    )
    transfers = tuple(db.scalars(transfer_query.order_by(
        StockTransfer.movement_date, StockTransfer.id)).all())

    theoretical_scopes, theoretical_sales = load_theoretical_inputs(
        db, company_id, start_date, end_date, branch_scope)
    return {"branches": branches, "products": products,
        "uploads": period_uploads, "current_uploads": completed_uploads,
        "snapshots": snapshots, "declarations": declarations,
        "purchase_lines": purchase_lines,
        "receipt_current_lines": receipt_current_lines, "movements": movements,
        "transfers": transfers, "theoretical_scopes": theoretical_scopes,
        "theoretical_sales": theoretical_sales}
