from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.models import (CompanyMembership, ModifierRecipeIngredient, Product,
    RecipeIngredient, RecipeVersion)


def register(client, email, company):
    response = client.post("/api/v1/auth/register", json={
        "full_name": "Cafe Owner", "email": email,
        "password": "StockPilot_Test_123!", "company_name": company,
        "industry": "CAFE", "country_code": "IN", "currency": "INR",
        "timezone": "Asia/Kolkata",
    })
    assert response.status_code == 201, response.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "StockPilot_Test_123!"})
    assert login.status_code == 200
    return login.cookies.get("stockpilot_session"), UUID(response.json()["company_id"])


def add_product(client, token, sku, name, unit, kind="LEGACY"):
    response = client.post("/api/v1/products", cookies={"stockpilot_session": token}, json={
        "sku": sku, "product_name": name, "unit_of_measure": unit,
        "product_kind": kind,
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_owner_can_classify_legacy_catalogue_items_and_filter_by_kind(test_environment):
    client, _ = test_environment
    owner, _ = register(client, "classify@example.com", "Classification Cafe")
    menu = add_product(client, owner, "CAP-001", "Cappuccino", "pcs")
    ingredient = add_product(client, owner, "BEAN-001", "Coffee beans", "g", "INGREDIENT")

    assert menu["product_kind"] == "LEGACY"
    classified = client.patch(f"/api/v1/products/{menu['id']}", cookies={"stockpilot_session": owner}, json={"product_kind": "MENU_ITEM"})
    assert classified.status_code == 200
    assert classified.json()["product_kind"] == "MENU_ITEM"
    assert [row["id"] for row in client.get("/api/v1/products?product_kind=MENU_ITEM", cookies={"stockpilot_session": owner}).json()] == [menu["id"]]
    assert [row["id"] for row in client.get("/api/v1/products?product_kind=INGREDIENT", cookies={"stockpilot_session": owner}).json()] == [ingredient["id"]]
    assert client.patch(f"/api/v1/products/{menu['id']}", cookies={"stockpilot_session": owner}, json={"product_kind": "DRINK"}).status_code == 422


def test_recipe_versions_preserve_history_and_resolve_by_business_date(test_environment):
    client, sessions = test_environment
    owner, company_id = register(client, "recipes@example.com", "Recipe Cafe")
    menu = add_product(client, owner, "CAP-100", "Cappuccino", "pcs", "MENU_ITEM")
    beans = add_product(client, owner, "BEANS", "Coffee beans", "g", "INGREDIENT")
    milk = add_product(client, owner, "MILK", "Milk", "ml", "INGREDIENT")

    group_response = client.post(f"/api/v1/recipes/menu-items/{menu['id']}/modifier-groups", cookies={"stockpilot_session": owner}, json={
        "name": "Milk choice", "selection_min": 0, "selection_max": 1,
        "options": ["Whole milk", "Oat milk"],
    })
    assert group_response.status_code == 201, group_response.text
    group = group_response.json()
    oat = next(option for option in group["options"] if option["name"] == "Oat milk")
    whole = next(option for option in group["options"] if option["name"] == "Whole milk")

    first = client.post(f"/api/v1/recipes/menu-items/{menu['id']}/versions", cookies={"stockpilot_session": owner}, json={
        "effective_from": "2026-01-01",
        "ingredients": [{"ingredient_product_id": beans["id"], "quantity": "18", "unit": "g"}],
        "modifier_ingredients": [
            {"modifier_option_id": oat["id"], "ingredient_product_id": milk["id"], "quantity": "120", "unit": "ml"},
            {"modifier_option_id": whole["id"], "ingredient_product_id": milk["id"], "quantity": "150", "unit": "ml"},
        ],
    })
    assert first.status_code == 201, first.text
    version_one = first.json()
    assert version_one["version"] == 1
    assert len(version_one["ingredients"]) == 1
    assert len(version_one["modifier_ingredients"]) == 2
    retrieved = client.get(f"/api/v1/recipes/menu-items/{menu['id']}", cookies={"stockpilot_session": owner})
    assert retrieved.status_code == 200
    assert len(retrieved.json()["versions"][0]["modifier_ingredients"]) == 2

    incompatible = client.post(f"/api/v1/recipes/menu-items/{menu['id']}/versions", cookies={"stockpilot_session": owner}, json={
        "effective_from": "2026-11-25",
        "ingredients": [{"ingredient_product_id": beans["id"], "quantity": "20", "unit": "kg"}],
    })
    assert incompatible.status_code == 422
    assert "No unit conversion" in incompatible.json()["detail"]

    second = client.post(f"/api/v1/recipes/menu-items/{menu['id']}/versions", cookies={"stockpilot_session": owner}, json={
        "effective_from": "2026-11-26",
        "ingredients": [
            {"ingredient_product_id": beans["id"], "quantity": "20", "unit": "g"},
            {"ingredient_product_id": milk["id"], "quantity": "140", "unit": "ml"},
        ],
    })
    assert second.status_code == 201, second.text
    assert second.json()["version"] == 2
    assert client.post(f"/api/v1/recipes/menu-items/{menu['id']}/versions", cookies={"stockpilot_session": owner}, json={
        "effective_from": "2026-11-20",
        "ingredients": [{"ingredient_product_id": beans["id"], "quantity": "22", "unit": "g"}],
    }).status_code == 422

    before_change = client.get(f"/api/v1/recipes/menu-items/{menu['id']}/version-for-date?business_date=2026-11-25", cookies={"stockpilot_session": owner})
    after_change = client.get(f"/api/v1/recipes/menu-items/{menu['id']}/version-for-date?business_date=2026-11-26", cookies={"stockpilot_session": owner})
    assert before_change.status_code == 200 and before_change.json()["id"] == version_one["id"]
    assert Decimal(str(before_change.json()["ingredients"][0]["quantity"])) == Decimal("18")
    assert after_change.status_code == 200 and after_change.json()["version"] == 2
    assert client.patch(f"/api/v1/recipes/menu-items/{menu['id']}/versions", cookies={"stockpilot_session": owner}, json={}).status_code == 405

    with sessions() as db:
        stored_v1 = db.get(RecipeVersion, UUID(version_one["id"]))
        assert stored_v1.version == 1 and stored_v1.effective_from == date(2026, 1, 1)
        ingredient_rows = db.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_version_id == stored_v1.id)).all()
        modifier_rows = db.scalars(select(ModifierRecipeIngredient).where(ModifierRecipeIngredient.recipe_version_id == stored_v1.id)).all()
        assert [row.quantity for row in ingredient_rows] == [Decimal("18.0000")]
        assert len(modifier_rows) == 2
        assert db.scalar(select(Product).where(Product.id == UUID(menu["id"]))).company_id == company_id


def test_recipe_and_modifier_apis_enforce_company_and_owner_writes(test_environment):
    client, sessions = test_environment
    owner_a, _ = register(client, "recipe-a@example.com", "Recipe Company A")
    owner_b, _ = register(client, "recipe-b@example.com", "Recipe Company B")
    menu = add_product(client, owner_a, "CAKE-A", "Cake A", "pcs", "MENU_ITEM")

    assert client.get(f"/api/v1/recipes/menu-items/{menu['id']}", cookies={"stockpilot_session": owner_b}).status_code == 404
    assert client.post(f"/api/v1/recipes/menu-items/{menu['id']}/modifier-groups", cookies={"stockpilot_session": owner_b}, json={
        "name": "Flavour", "options": ["Vanilla"],
    }).status_code == 404

    me = client.get("/api/v1/auth/me", cookies={"stockpilot_session": owner_a}).json()
    with sessions() as db:
        membership = db.scalar(select(CompanyMembership).where(CompanyMembership.company_id == UUID(me["company_id"])))
        for role in ("MANAGER", "STAFF", "ANALYST"):
            membership.role = role
            db.commit()
            assert client.get(f"/api/v1/recipes/menu-items/{menu['id']}", cookies={"stockpilot_session": owner_a}).status_code == 200
            denied_group = client.post(f"/api/v1/recipes/menu-items/{menu['id']}/modifier-groups", cookies={"stockpilot_session": owner_a}, json={
                "name": "Flavour", "options": ["Vanilla"],
            })
            assert denied_group.status_code == 403
            denied_classification = client.patch(f"/api/v1/products/{menu['id']}", cookies={"stockpilot_session": owner_a}, json={"product_kind": "LEGACY"})
            assert denied_classification.status_code == 403
