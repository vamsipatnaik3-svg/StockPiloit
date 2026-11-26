from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select

from app.models import (Branch, CompanyMembership, DailyUpload,
    ModifierGroup, ModifierOption, ModifierRecipeIngredient, Product,
    RecipeIngredient, RecipeVersion, SalesRecord, SalesRecordModifier)


PASSWORD = "StockPilot_Test_123!"
DAY1 = date(2026, 11, 25)
DAY2 = date(2026, 11, 26)


def register_owner(client, email="theory@example.com", company_name="Theory Cafe"):
    response = client.post("/api/v1/auth/register", json={
        "full_name": "Theory Owner", "email": email, "password": PASSWORD,
        "company_name": company_name, "industry": "CAFE", "country_code": "IN",
        "currency": "INR", "timezone": "Asia/Kolkata",
    })
    assert response.status_code == 201, response.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    return login.cookies.get("stockpilot_session"), UUID(response.json()["company_id"])


def seed_base(sessions, company_id, branch_count=1):
    with sessions() as db:
        membership = db.scalar(select(CompanyMembership).where(
            CompanyMembership.company_id == company_id))
        branches = [Branch(company_id=company_id, name=f"Branch {index + 1}",
            code=f"BR-{index + 1:03}", country_code="IN", timezone="Asia/Kolkata")
            for index in range(branch_count)]
        menu_a = Product(company_id=company_id, sku="MENU-A", product_name="Cappuccino",
            unit_of_measure="pcs", product_kind="MENU_ITEM")
        menu_b = Product(company_id=company_id, sku="MENU-B", product_name="Croissant",
            unit_of_measure="pcs", product_kind="MENU_ITEM")
        coffee = Product(company_id=company_id, sku="ING-COFFEE", product_name="Coffee beans",
            unit_of_measure="g", product_kind="INGREDIENT")
        milk = Product(company_id=company_id, sku="ING-MILK", product_name="Milk",
            unit_of_measure="ml", product_kind="INGREDIENT")
        db.add_all([*branches, menu_a, menu_b, coffee, milk])
        db.flush()
        db.commit()
        return membership.id, [branch.id for branch in branches], {
            "menu_a": menu_a.id, "menu_b": menu_b.id,
            "coffee": coffee.id, "milk": milk.id,
        }


def add_upload(db, membership_id, company_id, branch_id, business_date=DAY1,
               version=1, current=True, processing_status="COMPLETED"):
    upload = DailyUpload(company_id=company_id, branch_id=branch_id,
        business_date=business_date, uploaded_by_membership_id=membership_id,
        object_key=f"theory/{uuid4()}", original_filename=f"sales-v{version}.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_size_bytes=100, version=version, status="UPLOADED", is_current=current,
        processing_status=processing_status)
    db.add(upload)
    db.flush()
    return upload


def add_recipe(db, company_id, menu_id, ingredient_lines, effective_from=DAY1,
               version=1):
    recipe = RecipeVersion(company_id=company_id, menu_product_id=menu_id,
        version=version, effective_from=effective_from)
    db.add(recipe)
    db.flush()
    for ingredient_id, quantity, unit in ingredient_lines:
        db.add(RecipeIngredient(recipe_version_id=recipe.id,
            ingredient_product_id=ingredient_id, quantity=Decimal(str(quantity)), unit=unit))
    db.flush()
    return recipe


def add_sale(db, company_id, branch_id, upload, product_id, recipe_id,
             quantity, identity=None, business_date=None, granularity="AGGREGATED"):
    day = business_date or upload.business_date
    identity = identity or f"{upload.version}-{uuid4()}"
    record = SalesRecord(company_id=company_id, branch_id=branch_id,
        source_upload_id=upload.id, product_id=product_id,
        recipe_version_id=recipe_id, business_date=day, granularity=granularity,
        transaction_id=identity if granularity == "TRANSACTION" else None,
        line_id="1" if granularity == "TRANSACTION" else None,
        aggregate_id=identity if granularity == "AGGREGATED" else None,
        source_identity=identity, quantity=Decimal(str(quantity)),
        unit_price=Decimal("10"), discount_amount=Decimal(0),
        tax_amount=Decimal(0), net_amount=Decimal("10"))
    db.add(record)
    db.flush()
    return record


def query(client, token, extra="start_date=2026-11-25&end_date=2026-11-26"):
    return client.get("/api/v1/analytics/ingredient-consumption/theoretical?" + extra,
        cookies={"stockpilot_session": token})


def assert_decimal(actual, expected):
    assert Decimal(str(actual)) == Decimal(str(expected))


def test_basic_shared_ingredient_and_decimal_precision(test_environment):
    client, sessions = test_environment
    token, company_id = register_owner(client)
    membership_id, (branch_id,), products = seed_base(sessions, company_id)
    with sessions() as db:
        upload = add_upload(db, membership_id, company_id, branch_id)
        add_recipe(db, company_id, products["menu_a"], [(products["coffee"], "0.3333", "g")])
        add_recipe(db, company_id, products["menu_b"], [(products["coffee"], "0.5", "g")])
        add_sale(db, company_id, branch_id, upload, products["menu_a"],
            db.scalar(select(RecipeVersion.id).where(RecipeVersion.menu_product_id == products["menu_a"])), 3, "A-1")
        add_sale(db, company_id, branch_id, upload, products["menu_b"],
            db.scalar(select(RecipeVersion.id).where(RecipeVersion.menu_product_id == products["menu_b"])), 2, "B-1")
        db.commit()
    response = query(client, token, "start_date=2026-11-25&end_date=2026-11-25")
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    coffee = next(row for row in rows if row["ingredient_id"] == str(products["coffee"]))
    assert_decimal(coffee["base_theoretical_consumption"], "1.9999")
    assert_decimal(coffee["modifier_theoretical_consumption"], "0")
    assert_decimal(coffee["total_theoretical_consumption"], "1.9999")
    assert coffee["status"] == "COMPLETE"


def test_modifier_uses_selection_quantity_without_multiplying_by_sales_again(test_environment):
    client, sessions = test_environment
    token, company_id = register_owner(client)
    membership_id, (branch_id,), products = seed_base(sessions, company_id)
    with sessions() as db:
        upload = add_upload(db, membership_id, company_id, branch_id)
        recipe = add_recipe(db, company_id, products["menu_a"], [(products["coffee"], 2, "g")])
        group = ModifierGroup(company_id=company_id, menu_product_id=products["menu_a"],
            name="Extra shot", selection_min=0, selection_max=1)
        db.add(group); db.flush()
        option = ModifierOption(modifier_group_id=group.id, name="Double shot")
        db.add(option); db.flush()
        db.add(ModifierRecipeIngredient(recipe_version_id=recipe.id,
            modifier_option_id=option.id, ingredient_product_id=products["coffee"],
            quantity=Decimal("3"), unit="g"))
        sale = add_sale(db, company_id, branch_id, upload, products["menu_a"], recipe.id, 5, "CAP-1")
        db.add(SalesRecordModifier(sales_record_id=sale.id, modifier_option_id=option.id,
            selection_quantity=Decimal("2")))
        db.commit()
    response = query(client, token, "start_date=2026-11-25&end_date=2026-11-25")
    row = response.json()["items"][0]
    assert_decimal(row["base_theoretical_consumption"], "10.0000")
    # Two sold units selected this option: 2 × 3g = 6g, not 5 × 2 × 3g.
    assert_decimal(row["modifier_theoretical_consumption"], "6.0000")
    assert row["total_theoretical_consumption"] is None
    assert row["status"] == "INCOMPLETE"
    assert "MODIFIER_COMPLETENESS_UNKNOWN" in row["reason_codes"]


def test_complete_required_modifier_consumption_is_added_to_base(test_environment):
    client, sessions = test_environment
    token, company_id = register_owner(client)
    membership_id, (branch_id,), products = seed_base(sessions, company_id)
    with sessions() as db:
        upload = add_upload(db, membership_id, company_id, branch_id)
        recipe = add_recipe(db, company_id, products["menu_a"], [(products["coffee"], 2, "g")])
        group = ModifierGroup(company_id=company_id, menu_product_id=products["menu_a"],
            name="Milk choice", selection_min=1, selection_max=1)
        db.add(group); db.flush()
        option = ModifierOption(modifier_group_id=group.id, name="Oat milk")
        db.add(option); db.flush()
        db.add(ModifierRecipeIngredient(recipe_version_id=recipe.id,
            modifier_option_id=option.id, ingredient_product_id=products["milk"],
            quantity=Decimal("120"), unit="ml"))
        sale = add_sale(db, company_id, branch_id, upload, products["menu_a"], recipe.id, 2, "CAP-2")
        db.add(SalesRecordModifier(sales_record_id=sale.id, modifier_option_id=option.id,
            selection_quantity=Decimal("2")))
        db.commit()
    response = query(client, token, "start_date=2026-11-25&end_date=2026-11-25")
    assert response.status_code == 200
    rows = {row["ingredient_sku"]: row for row in response.json()["items"]}
    assert_decimal(rows["ING-COFFEE"]["total_theoretical_consumption"], "4.0000")
    assert_decimal(rows["ING-MILK"]["modifier_theoretical_consumption"], "240.0000")
    assert_decimal(rows["ING-MILK"]["base_theoretical_consumption"], "0")
    assert rows["ING-MILK"]["status"] == "COMPLETE"


def test_historical_pinned_recipe_versions_transaction_and_aggregate_sales(test_environment):
    client, sessions = test_environment
    token, company_id = register_owner(client)
    membership_id, (branch_id,), products = seed_base(sessions, company_id)
    with sessions() as db:
        first_upload = add_upload(db, membership_id, company_id, branch_id, DAY1)
        second_upload = add_upload(db, membership_id, company_id, branch_id, DAY2)
        first_recipe = add_recipe(db, company_id, products["menu_a"], [(products["coffee"], 10, "g")], DAY1, 1)
        second_recipe = add_recipe(db, company_id, products["menu_a"], [(products["coffee"], 20, "g")], DAY2, 2)
        add_sale(db, company_id, branch_id, first_upload, products["menu_a"], first_recipe.id,
            2, "AGG-1", DAY1, "AGGREGATED")
        add_sale(db, company_id, branch_id, second_upload, products["menu_a"], second_recipe.id,
            3, "TX-1", DAY2, "TRANSACTION")
        db.commit()
    response = query(client, token)
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    assert [(row["business_date"], row["status"]) for row in rows] == [
        ("2026-11-25", "COMPLETE"), ("2026-11-26", "COMPLETE")]
    assert_decimal(rows[0]["total_theoretical_consumption"], "20")
    assert_decimal(rows[1]["total_theoretical_consumption"], "60")


def test_missing_recipe_modifier_selection_and_modifier_mapping_are_incomplete(test_environment):
    client, sessions = test_environment
    token, company_id = register_owner(client)
    membership_id, (branch_id,), products = seed_base(sessions, company_id)
    with sessions() as db:
        upload = add_upload(db, membership_id, company_id, branch_id)
        menu_c = Product(company_id=company_id, sku="MENU-C", product_name="Cookie",
            unit_of_measure="pcs", product_kind="MENU_ITEM")
        db.add(menu_c); db.flush()
        recipe = add_recipe(db, company_id, products["menu_a"], [(products["coffee"], 4, "g")])
        group = ModifierGroup(company_id=company_id, menu_product_id=products["menu_a"],
            name="Flavour", selection_min=0, selection_max=2)
        db.add(group); db.flush()
        unmapped = ModifierOption(modifier_group_id=group.id, name="Peri Peri")
        mapped = ModifierOption(modifier_group_id=group.id, name="Vanilla")
        db.add_all([unmapped, mapped]); db.flush()
        sale_missing_map = add_sale(db, company_id, branch_id, upload, products["menu_a"], recipe.id, 1, "SALE-MAP")
        db.add(SalesRecordModifier(sales_record_id=sale_missing_map.id,
            modifier_option_id=unmapped.id, selection_quantity=Decimal(1)))
        add_sale(db, company_id, branch_id, upload, products["menu_b"], None, 1, "SALE-NO-RECIPE")
        empty_recipe = RecipeVersion(company_id=company_id,
            menu_product_id=products["menu_b"], version=1, effective_from=DAY1)
        db.add(empty_recipe); db.flush()
        add_sale(db, company_id, branch_id, upload, products["menu_b"], empty_recipe.id, 1, "SALE-EMPTY-RECIPE")
        valid_recipe = add_recipe(db, company_id, menu_c.id,
            [(products["coffee"], 1, "g")])
        valid_sale = add_sale(db, company_id, branch_id, upload, menu_c.id,
            valid_recipe.id, 1, "SALE-VALID")
        db.commit()
    response = query(client, token, "start_date=2026-11-25&end_date=2026-11-25")
    assert response.status_code == 200
    body = response.json()
    assert body["scopes"][0]["status"] == "INCOMPLETE"
    assert {"MISSING_RECIPE_VERSION", "MISSING_RECIPE_INGREDIENT_MAPPING", "MODIFIER_COMPLETENESS_UNKNOWN",
            "MISSING_MODIFIER_INGREDIENT_MAPPING"} <= set(body["scopes"][0]["reason_codes"])
    assert len(body["unresolved_sales"]) == 3
    assert str(valid_sale.id) not in {item["sales_record_id"] for item in body["unresolved_sales"]}
    coffee = next(row for row in body["items"] if row["ingredient_sku"] == "ING-COFFEE")
    assert_decimal(coffee["base_theoretical_consumption"], "5")
    assert coffee["total_theoretical_consumption"] is None


def test_null_modifier_selection_quantity_and_empty_optional_group_are_not_zero(test_environment):
    client, sessions = test_environment
    token, company_id = register_owner(client)
    membership_id, (branch_id,), products = seed_base(sessions, company_id)
    with sessions() as db:
        upload = add_upload(db, membership_id, company_id, branch_id)
        recipe = add_recipe(db, company_id, products["menu_a"], [(products["coffee"], 2, "g")])
        group = ModifierGroup(company_id=company_id, menu_product_id=products["menu_a"],
            name="Optional milk", selection_min=0, selection_max=1)
        db.add(group); db.flush()
        option = ModifierOption(modifier_group_id=group.id, name="Oat")
        db.add(option); db.flush()
        db.add(ModifierRecipeIngredient(recipe_version_id=recipe.id,
            modifier_option_id=option.id, ingredient_product_id=products["milk"],
            quantity=Decimal(100), unit="ml"))
        no_selection = add_sale(db, company_id, branch_id, upload, products["menu_a"], recipe.id, 1, "NO-MOD")
        null_selection = add_sale(db, company_id, branch_id, upload, products["menu_a"], recipe.id, 1, "NULL-MOD")
        db.add(SalesRecordModifier(sales_record_id=null_selection.id,
            modifier_option_id=option.id, selection_quantity=None))
        db.commit()
    response = query(client, token, "start_date=2026-11-25&end_date=2026-11-25")
    assert response.status_code == 200
    assert all(row["status"] == "INCOMPLETE" for row in response.json()["items"])
    assert all(row["modifier_theoretical_consumption"] is None for row in response.json()["items"])
    assert "MODIFIER_COMPLETENESS_UNKNOWN" in response.json()["scopes"][0]["reason_codes"]
    assert "MISSING_MODIFIER_SELECTION_QUANTITY" in response.json()["scopes"][0]["reason_codes"]


def test_unit_mismatch_inactive_ingredient_and_invalid_sales_quantity(test_environment):
    client, sessions = test_environment
    token, company_id = register_owner(client)
    membership_id, (branch_id,), products = seed_base(sessions, company_id)
    with sessions() as db:
        upload = add_upload(db, membership_id, company_id, branch_id)
        bad_unit_recipe = add_recipe(db, company_id, products["menu_a"], [(products["coffee"], 1, "kg")])
        add_sale(db, company_id, branch_id, upload, products["menu_a"], bad_unit_recipe.id, 1, "BAD-UNIT")
        milk_recipe = add_recipe(db, company_id, products["menu_b"], [(products["milk"], 1, "ml")])
        db.scalar(select(Product).where(Product.id == products["milk"])).is_active = False
        add_sale(db, company_id, branch_id, upload, products["menu_b"], milk_recipe.id, 1, "INACTIVE")
        # A second date has invalid directly-stored sales data. It must be diagnosed, not multiplied.
        bad_upload = add_upload(db, membership_id, company_id, branch_id, DAY2)
        negative_recipe = add_recipe(db, company_id, products["menu_a"], [(products["coffee"], 1, "g")], DAY2, 2)
        add_sale(db, company_id, branch_id, bad_upload, products["menu_a"], negative_recipe.id, -2, "NEGATIVE")
        db.commit()
    response = query(client, token)
    assert response.status_code == 200
    day_one = [row for row in response.json()["items"] if row["business_date"] == "2026-11-25"]
    assert any(row["status"] == "UNIT_MISMATCH" and "UNIT_MISMATCH" in row["reason_codes"] for row in day_one)
    assert any("INACTIVE_INGREDIENT" in row["reason_codes"] for row in day_one)
    day_two_scope = next(scope for scope in response.json()["scopes"] if scope["business_date"] == "2026-11-26")
    assert day_two_scope["status"] == "INVALID_DATA"
    assert "INVALID_SALES_QUANTITY" in day_two_scope["reason_codes"]


def test_only_current_completed_uploads_are_counted_and_provenance_returned(test_environment):
    client, sessions = test_environment
    token, company_id = register_owner(client)
    membership_id, (branch_id,), products = seed_base(sessions, company_id)
    with sessions() as db:
        old_upload = add_upload(db, membership_id, company_id, branch_id, version=1, current=False)
        current_upload = add_upload(db, membership_id, company_id, branch_id, version=2, current=True)
        failed_upload = add_upload(db, membership_id, company_id, branch_id, version=3,
            current=False, processing_status="VALIDATION_FAILED")
        recipe = add_recipe(db, company_id, products["menu_a"], [(products["coffee"], 3, "g")])
        # A corrected workbook can repeat the same source row identity. Both
        # records remain stored, while queries select the completed current version.
        add_sale(db, company_id, branch_id, old_upload, products["menu_a"], recipe.id, 100, "SAME-SOURCE-ROW")
        add_sale(db, company_id, branch_id, current_upload, products["menu_a"], recipe.id, 2, "SAME-SOURCE-ROW")
        add_sale(db, company_id, branch_id, failed_upload, products["menu_a"], recipe.id, 200, "FAILED")
        db.commit()
    response = query(client, token, "start_date=2026-11-25&end_date=2026-11-25")
    assert response.status_code == 200
    row = response.json()["items"][0]
    assert_decimal(row["total_theoretical_consumption"], "6.0000")
    assert row["source_uploads"] == [{"upload_id": response.json()["scopes"][0]["source_uploads"][0]["upload_id"], "version": 2}]
    assert response.json()["scopes"][0]["source_uploads"][0]["upload_id"] != str(old_upload.id)
    assert response.json()["scopes"][0]["source_uploads"][0]["upload_id"] != str(failed_upload.id)


def test_branch_and_company_isolation_and_owner_only_authorization(test_environment):
    client, sessions = test_environment
    token_a, company_a = register_owner(client, "theory-a@example.com", "Theory A")
    token_b, company_b = register_owner(client, "theory-b@example.com", "Theory B")
    membership_a, (branch_a, branch_other), products_a = seed_base(sessions, company_a, 2)
    membership_b, (branch_b,), products_b = seed_base(sessions, company_b)
    with sessions() as db:
        recipe_a = add_recipe(db, company_a, products_a["menu_a"], [(products_a["coffee"], 2, "g")])
        upload_a1 = add_upload(db, membership_a, company_a, branch_a)
        upload_a2 = add_upload(db, membership_a, company_a, branch_other)
        add_sale(db, company_a, branch_a, upload_a1, products_a["menu_a"], recipe_a.id, 2, "A1")
        add_sale(db, company_a, branch_other, upload_a2, products_a["menu_a"], recipe_a.id, 3, "A2")
        recipe_b = add_recipe(db, company_b, products_b["menu_a"], [(products_b["coffee"], 99, "g")])
        upload_b = add_upload(db, membership_b, company_b, branch_b)
        add_sale(db, company_b, branch_b, upload_b, products_b["menu_a"], recipe_b.id, 5, "B1")
        db.commit()
    branch_result = query(client, token_a,
        f"start_date=2026-11-25&end_date=2026-11-25&branch_id={branch_a}")
    assert branch_result.status_code == 200
    assert len(branch_result.json()["items"]) == 1
    assert_decimal(branch_result.json()["items"][0]["total_theoretical_consumption"], "4.0000")
    filtered_ingredient = query(client, token_a,
        f"start_date=2026-11-25&end_date=2026-11-25&ingredient_id={products_a['coffee']}")
    assert filtered_ingredient.status_code == 200
    assert {row["ingredient_id"] for row in filtered_ingredient.json()["items"]} == {str(products_a["coffee"])}
    all_branches = query(client, token_a, "start_date=2026-11-25&end_date=2026-11-25")
    assert {row["branch_id"] for row in all_branches.json()["items"]} == {str(branch_a), str(branch_other)}
    assert client.get("/api/v1/analytics/ingredient-consumption/theoretical?start_date=2026-11-25&end_date=2026-11-25&branch_id=" + str(branch_b),
        cookies={"stockpilot_session": token_a}).status_code == 404
    assert client.get("/api/v1/analytics/ingredient-consumption/theoretical?start_date=2026-11-25&end_date=2026-11-25&ingredient_id=" + str(products_b["coffee"]),
        cookies={"stockpilot_session": token_a}).status_code == 404
    with sessions() as db:
        membership = db.scalar(select(CompanyMembership).where(CompanyMembership.company_id == company_a))
        membership.role = "ANALYST"
        db.commit()
    assert query(client, token_a, "start_date=2026-11-25&end_date=2026-11-25").status_code == 403


def test_unavailable_scope_for_failed_upload_and_invalid_filters(test_environment):
    client, sessions = test_environment
    token, company_id = register_owner(client)
    membership_id, (branch_id,), _ = seed_base(sessions, company_id)
    with sessions() as db:
        add_upload(db, membership_id, company_id, branch_id, current=False,
            processing_status="VALIDATION_FAILED")
        db.commit()
    response = query(client, token, "start_date=2026-11-25&end_date=2026-11-25")
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["scopes"][0]["status"] == "UNAVAILABLE"
    assert "NO_COMPLETED_CURRENT_UPLOAD" in response.json()["scopes"][0]["reason_codes"]
    invalid_range = query(client, token, "start_date=2026-11-26&end_date=2026-11-25")
    assert invalid_range.status_code == 422
