"""Auth flow tests (DESIGN.md §14.1 "인증")."""

import pytest
from httpx import AsyncClient

from account_tests.server.conftest import extract_code

pytestmark = pytest.mark.asyncio

SIGNUP_BODY = {"id": "alice", "email": "alice@company.com", "password": "correct-horse"}


async def _signup(client: AsyncClient, **overrides: str) -> dict:
    body = {**SIGNUP_BODY, **overrides}
    response = await client.post("/account/v1/signup", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _signup_and_verify(client: AsyncClient, sent_emails, **overrides: str) -> str:
    await _signup(client, **overrides)
    code = extract_code(sent_emails[-1][2])
    user_id = overrides.get("id", SIGNUP_BODY["id"])
    response = await client.post(
        "/account/v1/verify-email", json={"id": user_id, "code": code}
    )
    assert response.status_code == 200, response.text
    return user_id


async def test_signup_success(client: AsyncClient, sent_emails):
    body = await _signup(client)
    assert body["status"] == "pending_verification"
    assert body["personal_org_id"] == "alice"
    assert len(sent_emails) == 1
    assert sent_emails[0][0] == "alice@company.com"


@pytest.mark.parametrize("bad_id", ["-alice", "alice-", "al--ice", "al_ice", "", "a..b"])
async def test_signup_rejects_invalid_id(client: AsyncClient, bad_id: str):
    response = await client.post("/account/v1/signup", json={**SIGNUP_BODY, "id": bad_id})
    assert response.status_code == 400


async def test_signup_rejects_disallowed_domain(client: AsyncClient):
    response = await client.post(
        "/account/v1/signup", json={**SIGNUP_BODY, "email": "alice@evil.com"}
    )
    assert response.status_code == 403


async def test_signup_rejects_duplicate_id(client: AsyncClient):
    await _signup(client)
    response = await client.post(
        "/account/v1/signup", json={**SIGNUP_BODY, "email": "alice2@company.com"}
    )
    assert response.status_code == 409


async def test_signup_rejects_duplicate_email(client: AsyncClient):
    await _signup(client)
    response = await client.post("/account/v1/signup", json={**SIGNUP_BODY, "id": "alice2"})
    assert response.status_code == 409


async def test_verify_email_wrong_code(client: AsyncClient, sent_emails):
    await _signup(client)
    response = await client.post(
        "/account/v1/verify-email", json={"id": "alice", "code": "000000"}
    )
    assert response.status_code == 400


async def test_resend_code_only_when_pending_or_locked(client: AsyncClient, sent_emails):
    user_id = await _signup_and_verify(client, sent_emails)
    response = await client.post("/account/v1/resend-code", json={"id": user_id})
    assert response.status_code == 409


async def test_resend_code_invalidates_previous(client: AsyncClient, sent_emails):
    await _signup(client)
    first_code = extract_code(sent_emails[-1][2])
    response = await client.post("/account/v1/resend-code", json={"id": "alice"})
    assert response.status_code == 202
    second_code = extract_code(sent_emails[-1][2])
    assert first_code != second_code

    stale = await client.post(
        "/account/v1/verify-email", json={"id": "alice", "code": first_code}
    )
    assert stale.status_code == 400

    fresh = await client.post(
        "/account/v1/verify-email", json={"id": "alice", "code": second_code}
    )
    assert fresh.status_code == 200


async def test_login_success(client: AsyncClient, sent_emails):
    await _signup_and_verify(client, sent_emails)
    response = await client.post(
        "/account/v1/login", json={"id": "alice", "password": SIGNUP_BODY["password"]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user"] == {
        "id": "alice",
        "email": "alice@company.com",
        "is_admin": False,
        "status": "active",
    }
    assert body["token"]


async def test_login_wrong_password(client: AsyncClient, sent_emails):
    await _signup_and_verify(client, sent_emails)
    response = await client.post(
        "/account/v1/login", json={"id": "alice", "password": "wrong"}
    )
    assert response.status_code == 401


async def test_login_before_verification_rejected(client: AsyncClient):
    await _signup(client)
    response = await client.post(
        "/account/v1/login", json={"id": "alice", "password": SIGNUP_BODY["password"]}
    )
    assert response.status_code == 403


async def test_login_lockout_after_threshold(client: AsyncClient, sent_emails):
    await _signup_and_verify(client, sent_emails)
    for _ in range(4):
        response = await client.post(
            "/account/v1/login", json={"id": "alice", "password": "wrong"}
        )
        assert response.status_code == 401

    fifth = await client.post("/account/v1/login", json={"id": "alice", "password": "wrong"})
    assert fifth.status_code == 423

    # Original (correct) password no longer works once locked.
    still_locked = await client.post(
        "/account/v1/login", json={"id": "alice", "password": SIGNUP_BODY["password"]}
    )
    assert still_locked.status_code == 423


async def test_unlock_flow(client: AsyncClient, sent_emails):
    await _signup_and_verify(client, sent_emails)
    for _ in range(5):
        await client.post("/account/v1/login", json={"id": "alice", "password": "wrong"})
    lockout_code = extract_code(sent_emails[-1][2])

    not_locked_yet = await client.post(
        "/account/v1/unlock", json={"id": "alice", "code": "000000", "new_password": "new-pass-1"}
    )
    assert not_locked_yet.status_code == 400  # wrong code, still exercised first

    response = await client.post(
        "/account/v1/unlock",
        json={"id": "alice", "code": lockout_code, "new_password": "new-pass-1"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "active"

    login_response = await client.post(
        "/account/v1/login", json={"id": "alice", "password": "new-pass-1"}
    )
    assert login_response.status_code == 200


async def test_unlock_rejected_when_not_locked(client: AsyncClient, sent_emails):
    await _signup_and_verify(client, sent_emails)
    response = await client.post(
        "/account/v1/unlock", json={"id": "alice", "code": "000000", "new_password": "new-pass-1"}
    )
    assert response.status_code == 409


async def _login_token(client: AsyncClient, sent_emails, user_id: str = "alice") -> str:
    await _signup_and_verify(client, sent_emails, id=user_id, email=f"{user_id}@company.com")
    response = await client.post(
        "/account/v1/login", json={"id": user_id, "password": SIGNUP_BODY["password"]}
    )
    return response.json()["token"]


async def test_change_password_requires_current(client: AsyncClient, sent_emails):
    token = await _login_token(client, sent_emails)
    response = await client.post(
        "/account/v1/change-password",
        json={"current_password": "wrong", "new_password": "new-pass-1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


async def test_change_password_success(client: AsyncClient, sent_emails):
    token = await _login_token(client, sent_emails)
    response = await client.post(
        "/account/v1/change-password",
        json={"current_password": SIGNUP_BODY["password"], "new_password": "new-pass-1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    login_response = await client.post(
        "/account/v1/login", json={"id": "alice", "password": "new-pass-1"}
    )
    assert login_response.status_code == 200


async def test_reset_password_request_same_response_regardless_of_existence(
    client: AsyncClient, sent_emails
):
    known = await client.post(
        "/account/v1/reset-password/request", json={"email": "nobody@company.com"}
    )
    await _signup_and_verify(client, sent_emails)
    unknown = await client.post(
        "/account/v1/reset-password/request", json={"email": "alice@company.com"}
    )
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert len(sent_emails) == 2  # signup verification + reset (none for the nonexistent email)


async def test_reset_password_confirm_flow(client: AsyncClient, sent_emails):
    await _signup_and_verify(client, sent_emails)
    await client.post("/account/v1/reset-password/request", json={"email": "alice@company.com"})
    reset_code = extract_code(sent_emails[-1][2])

    response = await client.post(
        "/account/v1/reset-password/confirm",
        json={"id": "alice", "code": reset_code, "new_password": "reset-pass-1"},
    )
    assert response.status_code == 200

    login_response = await client.post(
        "/account/v1/login", json={"id": "alice", "password": "reset-pass-1"}
    )
    assert login_response.status_code == 200


async def test_change_email_flow(client: AsyncClient, sent_emails):
    token = await _login_token(client, sent_emails)
    request_response = await client.post(
        "/account/v1/change-email/request",
        json={"new_email": "alice-new@company.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert request_response.status_code == 202

    # Old email still active until confirmed.
    whoami_login = await client.post(
        "/account/v1/login", json={"id": "alice", "password": SIGNUP_BODY["password"]}
    )
    assert whoami_login.status_code == 200

    code = extract_code(sent_emails[-1][2])
    confirm_response = await client.post(
        "/account/v1/change-email/confirm",
        json={"code": code},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["email"] == "alice-new@company.com"


async def test_change_email_rejects_disallowed_domain(client: AsyncClient, sent_emails):
    token = await _login_token(client, sent_emails)
    response = await client.post(
        "/account/v1/change-email/request",
        json={"new_email": "alice@evil.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400


async def test_change_email_rejects_email_in_use(client: AsyncClient, sent_emails):
    token_alice = await _login_token(client, sent_emails, user_id="alice")
    await _login_token(client, sent_emails, user_id="bob")
    response = await client.post(
        "/account/v1/change-email/request",
        json={"new_email": "bob@company.com"},
        headers={"Authorization": f"Bearer {token_alice}"},
    )
    assert response.status_code == 409


async def test_signup_seed_admin_promotion(client: AsyncClient, sent_emails):
    body = await _signup(client, id="admin", email="admin@company.com")
    assert body["status"] == "pending_verification"
    code = extract_code(sent_emails[-1][2])
    await client.post("/account/v1/verify-email", json={"id": "admin", "code": code})
    login_response = await client.post(
        "/account/v1/login", json={"id": "admin", "password": SIGNUP_BODY["password"]}
    )
    assert login_response.json()["user"]["is_admin"] is True
