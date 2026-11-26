from datetime import date
from decimal import Decimal

from app.models import (Branch, Company, DailyUpload, ModifierGroup,
    ModifierOption, ModifierRecipeIngredient, Product, RecipeIngredient,
    RecipeVersion, SalesRecord, SalesRecordModifier, User,
    CompanyMembership)


def test_product_kind_defaults_to_legacy_for_existing_create_call(test_environment):
    _, session_factory = test_environment
    with session_factory() as db:
        company = Company(name="Bakery", industry="cafe", country_code="IN", currency="INR", timezone="Asia/Kolkata")
        db.add(company)
        db.flush()
        product = Product(company_id=company.id, sku="OLD-001", product_name="Existing product", unit_of_measure="pcs")
        db.add(product)
        db.flush()

        assert product.product_kind == "LEGACY"
        assert db.get(Product, product.id).product_kind == "LEGACY"


def test_recipe_versions_and_sales_keep_the_selected_version_and_modifiers(test_environment):
    _, session_factory = test_environment
    with session_factory() as db:
        company = Company(name="Cafe", industry="cafe", country_code="IN", currency="INR", timezone="Asia/Kolkata")
        user = User(full_name="Owner", email="phase1@example.com", password_hash="test-hash")
        db.add_all([company, user])
        db.flush()
        membership = CompanyMembership(company_id=company.id, user_id=user.id, role="OWNER")
        db.add(membership)
        db.flush()
        branch = Branch(company_id=company.id, name="Main", code="MAIN", country_code="IN", timezone="Asia/Kolkata")
        db.add(branch)
        db.flush()
        upload = DailyUpload(company_id=company.id, branch_id=branch.id,
            business_date=date(2026, 11, 26), uploaded_by_membership_id=membership.id,
            object_key="phase1/workbook.xlsx", original_filename="workbook.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", version=1)
        db.add(upload)
        menu = Product(company_id=company.id, sku="CAP-001", product_name="Cappuccino",
            unit_of_measure="pcs", product_kind="MENU_ITEM")
        beans = Product(company_id=company.id, sku="BEAN-001", product_name="Coffee beans",
            unit_of_measure="g", product_kind="INGREDIENT")
        milk = Product(company_id=company.id, sku="MILK-001", product_name="Milk",
            unit_of_measure="ml", product_kind="INGREDIENT")
        db.add_all([menu, beans, milk])
        db.flush()

        first = RecipeVersion(company_id=company.id, menu_product_id=menu.id,
            version=1, effective_from=date(2026, 1, 1))
        second = RecipeVersion(company_id=company.id, menu_product_id=menu.id,
            version=2, effective_from=date(2026, 11, 26))
        group = ModifierGroup(company_id=company.id, menu_product_id=menu.id,
            name="Milk choice", selection_min=0, selection_max=1)
        db.add_all([first, second, group])
        db.flush()
        option = ModifierOption(modifier_group_id=group.id, name="Oat milk")
        db.add_all([
            RecipeIngredient(recipe_version_id=first.id, ingredient_product_id=beans.id,
                quantity=Decimal("18"), unit="g"),
            RecipeIngredient(recipe_version_id=second.id, ingredient_product_id=beans.id,
                quantity=Decimal("20"), unit="g"),
        ])
        db.add(option)
        db.flush()
        db.add(ModifierRecipeIngredient(recipe_version_id=first.id,
            modifier_option_id=option.id, ingredient_product_id=milk.id,
            quantity=Decimal("120"), unit="ml"))
        sale = SalesRecord(company_id=company.id, branch_id=branch.id,
            source_upload_id=upload.id, product_id=menu.id, recipe_version_id=first.id,
            business_date=date(2026, 11, 26), granularity="AGGREGATED",
            aggregate_id="DAY-MILK", source_identity="DAY-MILK:CAP-001",
            quantity=Decimal("2"), unit_price=Decimal("150"), discount_amount=Decimal("0"),
            tax_amount=Decimal("0"), net_amount=Decimal("300"))
        db.add(sale)
        db.flush()
        selection = SalesRecordModifier(sales_record_id=sale.id, modifier_option_id=option.id)
        db.add(selection)
        db.commit()

        persisted_sale = db.get(SalesRecord, sale.id)
        assert persisted_sale.recipe_version_id == first.id
        assert db.query(SalesRecordModifier).filter_by(sales_record_id=sale.id).one().modifier_option_id == option.id
        assert db.query(RecipeVersion).filter_by(menu_product_id=menu.id).count() == 2
