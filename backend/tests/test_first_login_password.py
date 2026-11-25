
def register_owner_and_login(client, email):
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "US008 Test Owner",
            "email": email,
            "password": "StockPilot_Test_123!",
            "company_name": "US008 Test Company",
            "industry": "grocery",
            "country_code": "IN",
            "currency": "INR",
            "timezone": "Asia/Kolkata",
        },
    )

    assert registration.status_code == 201

    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": "StockPilot_Test_123!",
        },
    )

    assert login.status_code == 200

    return registration.json(), login.cookies.get("stockpilot_session")


def create_employee_for_test(client, owner_token, email):
    branch_response = client.post(
        "/api/v1/branches",
        json={
            "name": "US008 Test Branch",
            "code": "US008",
            "address_line1": "Main Road",
            "address_line2": None,
            "city": "Hyderabad",
            "state": "Telangana",
            "postal_code": "500001",
            "country_code": "IN",
            "timezone": "Asia/Kolkata",
        },
        cookies={"stockpilot_session": owner_token},
    )

    assert branch_response.status_code == 201
    branch = branch_response.json()

    temporary_password = "Temporary_12345!"

    employee_response = client.post(
        "/api/v1/team/employees",
        json={
            "full_name": "US008 Test Employee",
            "email": email,
            "temporary_password": temporary_password,
            "role": "STAFF",
            "branch_ids": [branch["id"]],
        },
        cookies={"stockpilot_session": owner_token},
    )

    assert employee_response.status_code == 201

    return branch, temporary_password


def login_employee(client, email, password):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    return response


def test_employee_must_change_temporary_password_before_access(
    test_environment,
):
    client, _ = test_environment

    _, owner_token = register_owner_and_login(
        client,
        "us008.flow.owner@example.com",
    )

    branch, temporary_password = create_employee_for_test(
        client,
        owner_token,
        "us008.flow.employee@example.com",
    )

    login = login_employee(
        client,
        "us008.flow.employee@example.com",
        temporary_password,
    )

    assert login.status_code == 200
    assert login.json()["must_change_password"] is True

    employee_token = login.cookies.get("stockpilot_session")
    assert employee_token is not None

    employee_cookies = {
        "stockpilot_session": employee_token,
    }

    # Account information must remain accessible.
    me_response = client.get(
        "/api/v1/auth/me",
        cookies=employee_cookies,
    )

    assert me_response.status_code == 200
    assert me_response.json()["must_change_password"] is True

    # Business access must be blocked before password change.
    blocked_response = client.get(
        "/api/v1/branches",
        cookies=employee_cookies,
    )

    assert blocked_response.status_code == 403
    assert blocked_response.json()["detail"]["code"] == (
        "PASSWORD_CHANGE_REQUIRED"
    )

    # Change the temporary password.
    new_password = "Permanent_Employee_123!"

    change_response = client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": temporary_password,
            "new_password": new_password,
        },
        cookies=employee_cookies,
    )

    assert change_response.status_code == 200
    assert change_response.json()["must_change_password"] is False

    # The same session should remain valid.
    updated_me_response = client.get(
        "/api/v1/auth/me",
        cookies=employee_cookies,
    )

    assert updated_me_response.status_code == 200
    assert updated_me_response.json()["must_change_password"] is False

    # Assigned branch access should now work.
    branch_response = client.get(
        "/api/v1/branches",
        cookies=employee_cookies,
    )

    assert branch_response.status_code == 200
    assert len(branch_response.json()) == 1
    assert branch_response.json()[0]["id"] == branch["id"]

    # Old temporary password must no longer work.
    old_password_login = login_employee(
        client,
        "us008.flow.employee@example.com",
        temporary_password,
    )

    assert old_password_login.status_code == 401

    # New password must work.
    new_password_login = login_employee(
        client,
        "us008.flow.employee@example.com",
        new_password,
    )

    assert new_password_login.status_code == 200
    assert new_password_login.json()["must_change_password"] is False


def test_change_password_rejects_wrong_current_and_same_password(
    test_environment,
):
    client, _ = test_environment

    _, owner_token = register_owner_and_login(
        client,
        "us008.validation.owner@example.com",
    )

    _, temporary_password = create_employee_for_test(
        client,
        owner_token,
        "us008.validation.employee@example.com",
    )

    login = login_employee(
        client,
        "us008.validation.employee@example.com",
        temporary_password,
    )

    assert login.status_code == 200

    employee_token = login.cookies.get("stockpilot_session")
    cookies = {"stockpilot_session": employee_token}

    # Incorrect current password.
    wrong_password_response = client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "Wrong_Current_Password_123!",
            "new_password": "Permanent_Employee_123!",
        },
        cookies=cookies,
    )

    assert wrong_password_response.status_code == 400
    assert wrong_password_response.json()["detail"] == (
        "Current password is incorrect."
    )

    # New password cannot be identical to the current password.
    same_password_response = client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": temporary_password,
            "new_password": temporary_password,
        },
        cookies=cookies,
    )

    assert same_password_response.status_code == 400
    assert same_password_response.json()["detail"] == (
        "New password must be different from your current password."
    )

    # The account must still require a password change.
    me_response = client.get(
        "/api/v1/auth/me",
        cookies=cookies,
    )

    assert me_response.status_code == 200
    assert me_response.json()["must_change_password"] is True


def test_password_change_revokes_other_sessions_only(
    test_environment,
):
    client, _ = test_environment

    _, owner_token = register_owner_and_login(
        client,
        "us008.sessions.owner@example.com",
    )

    _, temporary_password = create_employee_for_test(
        client,
        owner_token,
        "us008.sessions.employee@example.com",
    )

    # Create two separate employee sessions.
    first_login = login_employee(
        client,
        "us008.sessions.employee@example.com",
        temporary_password,
    )

    second_login = login_employee(
        client,
        "us008.sessions.employee@example.com",
        temporary_password,
    )

    assert first_login.status_code == 200
    assert second_login.status_code == 200

    first_token = first_login.cookies.get("stockpilot_session")
    second_token = second_login.cookies.get("stockpilot_session")

    assert first_token is not None
    assert second_token is not None
    assert first_token != second_token

    # Change password using the first session.
    change_response = client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": temporary_password,
            "new_password": "Permanent_Employee_123!",
        },
        cookies={"stockpilot_session": first_token},
    )

    assert change_response.status_code == 200

    # The session used for the password change remains valid.
    first_session_response = client.get(
        "/api/v1/auth/me",
        cookies={"stockpilot_session": first_token},
    )

    assert first_session_response.status_code == 200

    # The other session must have been revoked.
    second_session_response = client.get(
        "/api/v1/auth/me",
        cookies={"stockpilot_session": second_token},
    )

    assert second_session_response.status_code == 401
