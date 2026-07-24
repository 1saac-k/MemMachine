"""Admin endpoint tests (DESIGN.md §14.1 "admin")."""

import httpx
import pytest
from httpx import AsyncClient

from account_tests.server.conftest import extract_code

pytestmark = pytest.mark.asyncio

SIGNUP_BODY = {"id": "alice", "email": "alice@company.com", "password": "correct-horse"}


async def _signup_login(client: AsyncClient, sent_emails, user_id: str, email: str | None = None) -> str:
    body = {**SIGNUP_BODY, "id": user_id, "email": email or f"{user_id}@company.com"}
    await client.post("/account/v1/signup", json=body)
    code = extract_code(sent_emails[-1][2])
    await client.post("/account/v1/verify-email", json={"id": user_id, "code": code})
    response = await client.post(
        "/account/v1/login", json={"id": user_id, "password": SIGNUP_BODY["password"]}
    )
    return response.json()["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_non_admin_forbidden_from_all_admin_endpoints(client: AsyncClient, sent_emails):
    token = await _signup_login(client, sent_emails, "alice")
    assert (await client.get("/account/v1/admin/users", headers=_auth(token))).status_code == 403
    assert (
        await client.post("/account/v1/admin/users/alice/deactivate", headers=_auth(token))
    ).status_code == 403
    assert (
        await client.post(
            "/account/v1/admin/users/alice/purge",
            json={"confirm_id": "alice"},
            headers=_auth(token),
        )
    ).status_code == 403
    assert (
        await client.post("/account/v1/admin/users/alice/revoke-tokens", headers=_auth(token))
    ).status_code == 403
    assert (
        await client.post("/account/v1/admin/sync-seed-admins", headers=_auth(token))
    ).status_code == 403
    assert (await client.get("/account/v1/admin/orgs", headers=_auth(token))).status_code == 403


async def test_list_users(client: AsyncClient, sent_emails):
    admin_token = await _signup_login(client, sent_emails, "admin", email="admin@company.com")
    await _signup_login(client, sent_emails, "alice")

    response = await client.get("/account/v1/admin/users", headers=_auth(admin_token))
    assert response.status_code == 200
    ids = {u["id"] for u in response.json()["users"]}
    assert ids == {"admin", "alice"}


async def test_deactivate_blocks_existing_token(client: AsyncClient, sent_emails):
    admin_token = await _signup_login(client, sent_emails, "admin", email="admin@company.com")
    alice_token = await _signup_login(client, sent_emails, "alice")

    response = await client.post(
        "/account/v1/admin/users/alice/deactivate", headers=_auth(admin_token)
    )
    assert response.status_code == 200
    assert response.json() == {"id": "alice", "status": "deactivated"}

    rejected = await client.get("/account/v1/tokens", headers=_auth(alice_token))
    assert rejected.status_code == 401


async def test_purge_requires_matching_confirm_id(client: AsyncClient, sent_emails):
    admin_token = await _signup_login(client, sent_emails, "admin", email="admin@company.com")
    await _signup_login(client, sent_emails, "alice")

    response = await client.post(
        "/account/v1/admin/users/alice/purge",
        json={"confirm_id": "not-alice"},
        headers=_auth(admin_token),
    )
    assert response.status_code == 400


async def test_purge_cascades_to_memmachine_and_deletes_account(
    client: AsyncClient, sent_emails, upstream
):
    admin_token = await _signup_login(client, sent_emails, "admin", email="admin@company.com")
    await _signup_login(client, sent_emails, "alice")

    def memmachine(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/projects/list":
            return httpx.Response(
                200,
                json=[
                    {"org_id": "alice", "project_id": "default"},
                    {"org_id": "bob", "project_id": "default"},
                ],
            )
        assert request.url.path == "/api/v2/projects/delete"
        return httpx.Response(200)

    upstream["handler"] = memmachine

    response = await client.post(
        "/account/v1/admin/users/alice/purge",
        json={"confirm_id": "alice"},
        headers=_auth(admin_token),
    )
    assert response.status_code == 200
    assert response.json() == {"id": "alice", "deleted_org_ids": ["alice"]}

    delete_calls = [r for r in upstream["requests"] if r.url.path == "/api/v2/projects/delete"]
    assert len(delete_calls) == 1
    import json as _json

    assert _json.loads(delete_calls[0].content) == {"org_id": "alice", "project_id": "default"}

    login_after_purge = await client.post(
        "/account/v1/login", json={"id": "alice", "password": SIGNUP_BODY["password"]}
    )
    assert login_after_purge.status_code == 401


async def test_revoke_tokens_invalidates_all_sessions(client: AsyncClient, sent_emails):
    admin_token = await _signup_login(client, sent_emails, "admin", email="admin@company.com")
    alice_token_a = await _signup_login(client, sent_emails, "alice")
    login_again = await client.post(
        "/account/v1/login", json={"id": "alice", "password": SIGNUP_BODY["password"]}
    )
    alice_token_b = login_again.json()["token"]

    response = await client.post(
        "/account/v1/admin/users/alice/revoke-tokens", headers=_auth(admin_token)
    )
    assert response.status_code == 200
    assert response.json() == {"id": "alice", "revoked_count": 2}

    assert (await client.get("/account/v1/tokens", headers=_auth(alice_token_a))).status_code == 401
    assert (await client.get("/account/v1/tokens", headers=_auth(alice_token_b))).status_code == 401


async def test_sync_seed_admins_promotes_and_demotes(client: AsyncClient, sent_emails, config):
    admin_token = await _signup_login(client, sent_emails, "admin", email="admin@company.com")
    await _signup_login(client, sent_emails, "alice")

    config.auth.seed_admins = ["alice@company.com"]  # admin@company.com no longer seeded
    response = await client.post(
        "/account/v1/admin/sync-seed-admins", headers=_auth(admin_token)
    )
    assert response.status_code == 200
    assert response.json() == {"promoted": ["alice"], "demoted": ["admin"]}


async def test_sync_seed_admins_refuses_to_leave_zero_admins(
    client: AsyncClient, sent_emails, config
):
    admin_token = await _signup_login(client, sent_emails, "admin", email="admin@company.com")

    config.auth.seed_admins = []
    response = await client.post(
        "/account/v1/admin/sync-seed-admins", headers=_auth(admin_token)
    )
    assert response.status_code == 409


async def test_list_orgs_shows_member_counts(client: AsyncClient, sent_emails):
    admin_token = await _signup_login(client, sent_emails, "admin", email="admin@company.com")
    alice_token = await _signup_login(client, sent_emails, "alice")
    await _signup_login(client, sent_emails, "bob")
    await client.post("/account/v1/orgs", json={"org_id": "team-a"}, headers=_auth(alice_token))
    await client.post(
        "/account/v1/orgs/team-a/members", json={"user_id": "bob"}, headers=_auth(alice_token)
    )

    response = await client.get("/account/v1/admin/orgs", headers=_auth(admin_token))
    assert response.status_code == 200
    by_id = {o["org_id"]: o for o in response.json()["orgs"]}
    assert by_id["alice"]["member_count"] == 1
    assert by_id["team-a"]["member_count"] == 2
