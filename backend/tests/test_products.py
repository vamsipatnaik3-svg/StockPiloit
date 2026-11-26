from uuid import UUID

from sqlalchemy import select

from app.models import Product


def register_login(client, email, company):
    response = client.post("/api/v1/auth/register", json={
        "full_name": "Catalogue Owner", "email": email,
        "password": "StockPilot_Test_123!", "company_name": company,
        "industry": "grocery", "country_code": "IN", "currency": "INR",
        "timezone": "Asia/Kolkata",
    })
    assert response.status_code == 201
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "StockPilot_Test_123!"})
    assert login.status_code == 200
    return login.cookies.get("stockpilot_session")


def product_payload(sku="SKU-001"):
    return {"sku": sku, "product_name": "Tea", "unit_of_measure": "EA"}


def test_product_catalogue_is_company_scoped_and_sku_unique(test_environment):
    client, sessions = test_environment
    token_a = register_login(client, "owner-a@example.com", "Company A")
    token_b = register_login(client, "owner-b@example.com", "Company B")

    created = client.post("/api/v1/products", json=product_payload(), cookies={"stockpilot_session": token_a})
    assert created.status_code == 201
    assert client.post("/api/v1/products", json=product_payload(), cookies={"stockpilot_session": token_a}).status_code == 409
    other = client.post("/api/v1/products", json=product_payload(), cookies={"stockpilot_session": token_b})
    assert other.status_code == 201
    assert client.get("/api/v1/products", cookies={"stockpilot_session": token_b}).json()[0]["id"] == other.json()["id"]
    assert client.get(f"/api/v1/products/{created.json()['id']}", cookies={"stockpilot_session": token_b}).status_code == 404

    with sessions() as db:
        assert db.scalar(select(Product).where(Product.sku == "SKU-001")) is not None


def test_product_catalogue_is_owner_write_only(test_environment):
    client, _ = test_environment
    token = register_login(client, "owner-role@example.com", "Role Company")
    response = client.get("/api/v1/auth/me", cookies={"stockpilot_session": token})
    company_id = response.json()["company_id"]
    from app.models import CompanyMembership
    from sqlalchemy import select
    with test_environment[1]() as db:
        membership = db.scalar(select(CompanyMembership).where(CompanyMembership.company_id == UUID(company_id)))
        membership.role = "ANALYST"
        db.commit()
    assert client.post("/api/v1/products", json=product_payload(), cookies={"stockpilot_session": token}).status_code == 403
