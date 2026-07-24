"""Token issuance/list/revoke tests (DESIGN.md §14.1 "토큰")."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from account_tests.server.conftest import extract_code
from memmachine_account.server.config import AppConfig
from memmachine_account.server.storage import (
    User,
    UserStatus,
    create_engine,
    create_session_factory,
)

pytestmark = pytest.mark.asyncio

SIGNUP_BODY = {"id": "alice", "email": "alice@company.com", "password": "correct-horse"}


async def _login(client: AsyncClient, sent_emails, user_id: str = "alice") -> str:
    body = {**SIGNUP_BODY, "id": user_id, "email": f"{user_id}@company.com"}
    await client.post("/account/v1/signup", json=body)
    code = extract_code(sent_emails[-1][2])
    await client.post("/account/v1/verify-email", json={"id": user_id, "code": code})
    response = await client.post(
        "/account/v1/login", json={"id": user_id, "password": SIGNUP_BODY["password"]}
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


async def _set_user_status(config: AppConfig, user_id: str, status: UserStatus) -> None:
    """Directly flip a user's status (admin endpoint for this lands in M6)."""
    engine = create_engine(config.storage.sqlite_path)
    factory = create_session_factory(engine)
    async with factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one()
        user.status = status.value
        await session.commit()
    await engine.dispose()


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_revoked_token_is_rejected(client: AsyncClient, sent_emails, config: AppConfig):
    token = await _login(client, sent_emails)
    list_response = await client.get("/account/v1/tokens", headers=_auth_headers(token))
    token_id = list_response.json()["tokens"][0]["token_id"]

    revoke_response = await client.delete(
        f"/account/v1/tokens/{token_id}", headers=_auth_headers(token)
    )
    assert revoke_response.status_code == 204

    rejected = await client.get("/account/v1/tokens", headers=_auth_headers(token))
    assert rejected.status_code == 401


async def test_deactivated_user_token_is_rejected_even_if_not_revoked(
    client: AsyncClient, sent_emails, config: AppConfig
):
    token = await _login(client, sent_emails)
    await _set_user_status(config, "alice", UserStatus.DEACTIVATED)

    response = await client.get("/account/v1/tokens", headers=_auth_headers(token))
    assert response.status_code == 401


async def test_token_list_never_shows_raw_value(client: AsyncClient, sent_emails):
    token = await _login(client, sent_emails)
    response = await client.get("/account/v1/tokens", headers=_auth_headers(token))
    assert response.status_code == 200
    body = response.json()
    assert len(body["tokens"]) == 1
    entry = body["tokens"][0]
    assert set(entry) == {"token_id", "created_at", "last_used_at"}
    assert token not in str(body)


async def test_multiple_device_tokens_all_listed(client: AsyncClient, sent_emails):
    token_a = await _login(client, sent_emails)
    login_again = await client.post(
        "/account/v1/login", json={"id": "alice", "password": SIGNUP_BODY["password"]}
    )
    token_b = login_again.json()["token"]
    assert token_a != token_b

    response = await client.get("/account/v1/tokens", headers=_auth_headers(token_a))
    assert len(response.json()["tokens"]) == 2


async def test_revoke_missing_token_id_is_404(client: AsyncClient, sent_emails):
    token = await _login(client, sent_emails)
    response = await client.delete(
        "/account/v1/tokens/does-not-exist", headers=_auth_headers(token)
    )
    assert response.status_code == 404


async def test_cannot_revoke_another_users_token(client: AsyncClient, sent_emails):
    token_alice = await _login(client, sent_emails, user_id="alice")
    token_bob = await _login(client, sent_emails, user_id="bob")

    bob_tokens = await client.get("/account/v1/tokens", headers=_auth_headers(token_bob))
    bob_token_id = bob_tokens.json()["tokens"][0]["token_id"]

    response = await client.delete(
        f"/account/v1/tokens/{bob_token_id}", headers=_auth_headers(token_alice)
    )
    assert response.status_code == 404

    # Bob's token still works.
    still_valid = await client.get("/account/v1/tokens", headers=_auth_headers(token_bob))
    assert still_valid.status_code == 200


async def test_logout_revokes_current_token(client: AsyncClient, sent_emails):
    token = await _login(client, sent_emails)
    logout_response = await client.post("/account/v1/logout", headers=_auth_headers(token))
    assert logout_response.status_code == 204

    rejected = await client.get("/account/v1/tokens", headers=_auth_headers(token))
    assert rejected.status_code == 401


async def test_missing_authorization_header_is_401(client: AsyncClient):
    response = await client.get("/account/v1/tokens")
    assert response.status_code == 401
