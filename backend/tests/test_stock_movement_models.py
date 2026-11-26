from datetime import date
from decimal import Decimal
import uuid

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import (Branch, Company, CompanyMembership, DailyUpload,
    InventorySnapshot, Product, PurchaseLine, PurchaseReceiptCurrentLine,
    PurchaseReceiptIdentity, StockCoverageDeclaration, StockMovement,
    StockMovementReasonCode, StockTransfer, User)


@pytest.fixture
def stock_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    company = Company(name="A", industry="CAFE", country_code="IN", currency="INR", timezone="Asia/Kolkata")
    other_company = Company(name="B", industry="CAFE", country_code="IN", currency="INR", timezone="Asia/Kolkata")
    user = User(full_name="Owner", email="owner@example.test", password_hash="hash")
    other_user = User(full_name="Other", email="other@example.test", password_hash="hash")
    db.add_all([company, other_company, user, other_user])
    db.flush()
    membership = CompanyMembership(company_id=company.id, user_id=user.id, role="OWNER")
    other_membership = CompanyMembership(company_id=other_company.id, user_id=other_user.id, role="OWNER")
    db.add_all([membership, other_membership])
    db.flush()
    branch = Branch(company_id=company.id, name="Main", code="M", country_code="IN", timezone="Asia/Kolkata")
    destination = Branch(company_id=company.id, name="Second", code="S", country_code="IN", timezone="Asia/Kolkata")
    foreign_branch = Branch(company_id=other_company.id, name="Other", code="O", country_code="IN", timezone="Asia/Kolkata")
    db.add_all([branch, destination, foreign_branch])
    db.flush()
    ingredient = Product(company_id=company.id, sku="COFFEE", product_name="Coffee", unit_of_measure="g", product_kind="INGREDIENT")
    other_ingredient = Product(company_id=other_company.id, sku="COFFEE", product_name="Coffee", unit_of_measure="g", product_kind="INGREDIENT")
    db.add_all([ingredient, other_ingredient])
    db.flush()
    upload1 = DailyUpload(company_id=company.id, branch_id=branch.id, business_date=date(2026, 11, 25),
        uploaded_by_membership_id=membership.id, object_key="one", original_filename="one.xlsx",
        content_type="application/xlsx", version=1, status="UPLOADED", is_current=False,
        processing_status="COMPLETED")
    upload2 = DailyUpload(company_id=company.id, branch_id=branch.id, business_date=date(2026, 11, 25),
        uploaded_by_membership_id=membership.id, object_key="two", original_filename="two.xlsx",
        content_type="application/xlsx", version=2, status="UPLOADED", is_current=True,
        processing_status="COMPLETED")
    db.add_all([upload1, upload2])
    db.flush()
    db.add_all([
        StockMovementReasonCode(code="WASTE_SPOILAGE", movement_type="WASTE", label="Spoilage"),
        StockMovementReasonCode(code="COUNT_DOWN", movement_type="NEGATIVE_ADJUSTMENT", label="Count correction"),
    ])
    db.commit()
    yield {
        "db": db, "company": company, "other_company": other_company, "membership": membership,
        "other_membership": other_membership, "branch": branch, "destination": destination,
        "foreign_branch": foreign_branch, "ingredient": ingredient,
        "other_ingredient": other_ingredient, "upload1": upload1, "upload2": upload2,
    }
    db.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def manual_movement(ctx, **overrides):
    values = dict(
        company_id=ctx["company"].id, branch_id=ctx["branch"].id,
        ingredient_product_id=ctx["ingredient"].id, movement_date=date(2026, 11, 25),
        movement_type="WASTE", quantity=Decimal("1.2500"), unit="g",
        origin_type="MANUAL", physical_event_id=uuid.uuid4(), reason_code="WASTE_SPOILAGE",
        created_by_user_id=ctx["membership"].user_id,
    )
    values.update(overrides)
    return StockMovement(**values)


def test_movement_positive_quantity_and_known_type_constraints(stock_db):
    db = stock_db["db"]
    db.add(manual_movement(stock_db))
    db.commit()

    for changes in ({"quantity": Decimal("0")}, {"quantity": Decimal("-1")},
                    {"movement_type": "UNCLASSIFIED"}):
        db.add(manual_movement(stock_db, **changes))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_reason_code_must_match_movement_type(stock_db):
    db = stock_db["db"]
    db.add(manual_movement(stock_db, movement_type="NEGATIVE_ADJUSTMENT",
                           reason_code="WASTE_SPOILAGE"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


@pytest.mark.parametrize("changes", [
    {"company_id": uuid.uuid4()},
    {"branch_id": None},
    {"unit": "ml"},
    {"ingredient_product_id": uuid.uuid4()},
])
def test_movement_enforces_company_branch_ingredient_and_canonical_unit(stock_db, changes):
    db = stock_db["db"]
    values = dict(changes)
    if values.get("branch_id") is None:
        values["branch_id"] = stock_db["foreign_branch"].id
    db.add(manual_movement(stock_db, **values))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_receipt_identity_is_unique_within_company_branch(stock_db):
    db = stock_db["db"]
    ident = PurchaseReceiptIdentity(company_id=stock_db["company"].id,
        branch_id=stock_db["branch"].id, receipt_event_id="event-001")
    db.add(ident)
    db.commit()
    db.add(PurchaseReceiptIdentity(company_id=stock_db["company"].id,
        branch_id=stock_db["branch"].id, receipt_event_id="event-001"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_purchase_receipt_movement_must_link_once_to_compatible_line(stock_db):
    db = stock_db["db"]
    line = PurchaseLine(company_id=stock_db["company"].id, branch_id=stock_db["branch"].id,
        source_upload_id=stock_db["upload2"].id, product_id=stock_db["ingredient"].id,
        receipt_id="R-1", receipt_line_id="1", business_date=date(2026, 11, 25),
        receipt_date=date(2026, 11, 25), quantity_received=Decimal("5"), purchase_unit="g")
    db.add(line)
    db.flush()
    values = dict(company_id=stock_db["company"].id, branch_id=stock_db["branch"].id,
        ingredient_product_id=stock_db["ingredient"].id, movement_date=date(2026, 11, 25),
        movement_type="PURCHASE_RECEIPT", quantity=Decimal("5"), unit="g",
        source_upload_id=stock_db["upload2"].id, purchase_line_id=line.id, origin_type="UPLOAD",
        physical_event_id=uuid.uuid4())
    db.add(StockMovement(**values))
    db.commit()
    db.add(StockMovement(**{**values, "id": uuid.uuid4(), "physical_event_id": uuid.uuid4()}))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_inventory_and_purchase_rows_can_be_retained_per_upload_version(stock_db):
    db = stock_db["db"]
    for upload in (stock_db["upload1"], stock_db["upload2"]):
        db.add(InventorySnapshot(company_id=stock_db["company"].id, branch_id=stock_db["branch"].id,
            source_upload_id=upload.id, product_id=stock_db["ingredient"].id,
            business_date=upload.business_date, batch_number="LOT-1", opening_quantity=Decimal("10"),
            closing_quantity=Decimal("9"), unit="g"))
        db.add(PurchaseLine(company_id=stock_db["company"].id, branch_id=stock_db["branch"].id,
            source_upload_id=upload.id, product_id=stock_db["ingredient"].id,
            receipt_id="R-1", receipt_line_id="1", business_date=upload.business_date,
            receipt_date=upload.business_date, quantity_received=Decimal("1"), purchase_unit="g"))
    db.commit()
    assert db.scalar(select(text("count(*)")).select_from(InventorySnapshot)) == 2
    assert db.scalar(select(text("count(*)")).select_from(PurchaseLine)) == 2
    assert db.scalar(select(DailyUpload.id).where(DailyUpload.is_current.is_(True))) == stock_db["upload2"].id


def test_current_receipt_pointer_and_coverage_uniqueness(stock_db):
    db = stock_db["db"]
    ident = PurchaseReceiptIdentity(company_id=stock_db["company"].id,
        branch_id=stock_db["branch"].id, receipt_event_id="receipt-event-2")
    db.add(ident)
    db.flush()
    line = PurchaseLine(company_id=stock_db["company"].id, branch_id=stock_db["branch"].id,
        source_upload_id=stock_db["upload2"].id, product_id=stock_db["ingredient"].id,
        receipt_id="R-2", receipt_line_id="2", business_date=date(2026, 11, 25),
        receipt_date=date(2026, 11, 25), quantity_received=Decimal("2"), purchase_unit="g",
        receipt_identity_id=ident.id)
    db.add(line)
    db.flush()
    db.add(PurchaseReceiptCurrentLine(receipt_identity_id=ident.id,
        company_id=stock_db["company"].id, branch_id=stock_db["branch"].id,
        purchase_line_id=line.id))
    coverage = StockCoverageDeclaration(company_id=stock_db["company"].id,
        branch_id=stock_db["branch"].id, business_date=date(2026, 11, 25),
        source_upload_id=stock_db["upload2"].id, ingredient_product_id=stock_db["ingredient"].id,
        unit="g", coverage_dimension="MOVEMENT_CATEGORY", scope_type="ALL_BATCHES",
        movement_type="WASTE", status="COMPLETE")
    db.add(coverage)
    db.commit()
    db.add(StockCoverageDeclaration(company_id=stock_db["company"].id,
        branch_id=stock_db["branch"].id, business_date=date(2026, 11, 25),
        source_upload_id=stock_db["upload2"].id, ingredient_product_id=stock_db["ingredient"].id,
        unit="g", coverage_dimension="MOVEMENT_CATEGORY", scope_type="ALL_BATCHES",
        movement_type="WASTE", status="UNREPORTED"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_transfer_enforces_company_and_distinct_branch_relationships(stock_db):
    db = stock_db["db"]
    wrong_company_transfer = StockTransfer(company_id=stock_db["company"].id,
        ingredient_product_id=stock_db["ingredient"].id, source_branch_id=stock_db["branch"].id,
        destination_branch_id=stock_db["foreign_branch"].id, movement_date=date(2026, 11, 25),
        quantity=Decimal("2"), unit="g", created_by_user_id=stock_db["membership"].user_id)
    db.add(wrong_company_transfer)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_stock_movement_tables_have_postgres_deferred_transfer_pairing():
    from pathlib import Path

    migration = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "4c010a9b7d21_stock_movement_foundation.py"
    source = migration.read_text()
    assert "DEFERRABLE INITIALLY DEFERRED" in source
    assert "exactly one matching inflow and outflow leg" in source
    assert "CREATE CONSTRAINT TRIGGER trg_tavuno_transfer_pair_movement" in source
    assert "CREATE CONSTRAINT TRIGGER trg_tavuno_transfer_pair_parent" in source
