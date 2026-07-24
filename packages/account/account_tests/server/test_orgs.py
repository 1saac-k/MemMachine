"""Org/membership tests (DESIGN.md §14.1 "org/멤버십")."""

import pytest
from httpx import AsyncClient

from account_tests.server.conftest import extract_code

pytestmark = pytest.mark.asyncio

SIGNUP_BODY = {"id": "alice", "email": "alice@company.com", "password": "correct-horse"}


async def _signup_login(client: AsyncClient, sent_emails, user_id: str) -> str:
    body = {**SIGNUP_BODY, "id": user_id, "email": f"{user_id}@company.com"}
    await client.post("/account/v1/signup", json=body)
    code = extract_code(sent_emails[-1][2])
    await client.post("/account/v1/verify-email", json={"id": user_id, "code": code})
    response = await client.post(
        "/account/v1/login", json={"id": user_id, "password": SIGNUP_BODY["password"]}
    )
    return response.json()["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_create_org_success(client: AsyncClient, sent_emails):
    token = await _signup_login(client, sent_emails, "alice")
    response = await client.post(
        "/account/v1/orgs", json={"org_id": "team-a"}, headers=_auth(token)
    )
    assert response.status_code == 201
    assert response.json() == {"org_id": "team-a", "kind": "shared", "role": "owner"}


@pytest.mark.parametrize("bad_org_id", ["-team", "team-", "team--a", "Team", "team.a", ""])
async def test_create_org_rejects_invalid_org_id(client: AsyncClient, sent_emails, bad_org_id: str):
    token = await _signup_login(client, sent_emails, "alice")
    response = await client.post(
        "/account/v1/orgs", json={"org_id": bad_org_id}, headers=_auth(token)
    )
    assert response.status_code == 400


async def test_create_org_collides_with_personal_org_id(client: AsyncClient, sent_emails):
    token = await _signup_login(client, sent_emails, "alice")
    response = await client.post(
        "/account/v1/orgs", json={"org_id": "alice"}, headers=_auth(token)
    )
    assert response.status_code == 409


async def test_personal_org_rejects_all_membership_operations(client: AsyncClient, sent_emails):
    token_alice = await _signup_login(client, sent_emails, "alice")
    await _signup_login(client, sent_emails, "bob")

    add = await client.post(
        "/account/v1/orgs/alice/members",
        json={"user_id": "bob"},
        headers=_auth(token_alice),
    )
    assert add.status_code == 400

    remove = await client.delete(
        "/account/v1/orgs/alice/members/bob", headers=_auth(token_alice)
    )
    assert remove.status_code == 400

    set_role = await client.post(
        "/account/v1/orgs/alice/members/bob/set-role",
        json={"role": "owner"},
        headers=_auth(token_alice),
    )
    assert set_role.status_code == 400

    leave = await client.post("/account/v1/orgs/alice/leave", headers=_auth(token_alice))
    assert leave.status_code == 400


async def test_add_member_requires_owner(client: AsyncClient, sent_emails):
    token_alice = await _signup_login(client, sent_emails, "alice")
    token_bob = await _signup_login(client, sent_emails, "bob")
    await client.post("/account/v1/orgs", json={"org_id": "team-a"}, headers=_auth(token_alice))

    response = await client.post(
        "/account/v1/orgs/team-a/members", json={"user_id": "bob"}, headers=_auth(token_bob)
    )
    assert response.status_code == 403


async def test_add_member_nonexistent_user(client: AsyncClient, sent_emails):
    token_alice = await _signup_login(client, sent_emails, "alice")
    await client.post("/account/v1/orgs", json={"org_id": "team-a"}, headers=_auth(token_alice))
    response = await client.post(
        "/account/v1/orgs/team-a/members",
        json={"user_id": "nobody"},
        headers=_auth(token_alice),
    )
    assert response.status_code == 404


async def test_add_member_already_member(client: AsyncClient, sent_emails):
    token_alice = await _signup_login(client, sent_emails, "alice")
    await _signup_login(client, sent_emails, "bob")
    await client.post("/account/v1/orgs", json={"org_id": "team-a"}, headers=_auth(token_alice))
    await client.post(
        "/account/v1/orgs/team-a/members", json={"user_id": "bob"}, headers=_auth(token_alice)
    )
    response = await client.post(
        "/account/v1/orgs/team-a/members", json={"user_id": "bob"}, headers=_auth(token_alice)
    )
    assert response.status_code == 409


async def test_remove_last_owner_rejected(client: AsyncClient, sent_emails):
    token_alice = await _signup_login(client, sent_emails, "alice")
    await client.post("/account/v1/orgs", json={"org_id": "team-a"}, headers=_auth(token_alice))
    response = await client.delete(
        "/account/v1/orgs/team-a/members/alice", headers=_auth(token_alice)
    )
    assert response.status_code == 409


async def test_remove_member_success(client: AsyncClient, sent_emails):
    token_alice = await _signup_login(client, sent_emails, "alice")
    await _signup_login(client, sent_emails, "bob")
    await client.post("/account/v1/orgs", json={"org_id": "team-a"}, headers=_auth(token_alice))
    await client.post(
        "/account/v1/orgs/team-a/members", json={"user_id": "bob"}, headers=_auth(token_alice)
    )
    response = await client.delete(
        "/account/v1/orgs/team-a/members/bob", headers=_auth(token_alice)
    )
    assert response.status_code == 204


async def test_set_role_demote_last_owner_rejected(client: AsyncClient, sent_emails):
    token_alice = await _signup_login(client, sent_emails, "alice")
    await client.post("/account/v1/orgs", json={"org_id": "team-a"}, headers=_auth(token_alice))
    response = await client.post(
        "/account/v1/orgs/team-a/members/alice/set-role",
        json={"role": "member"},
        headers=_auth(token_alice),
    )
    assert response.status_code == 409


async def test_set_role_promote_then_original_owner_can_leave(client: AsyncClient, sent_emails):
    token_alice = await _signup_login(client, sent_emails, "alice")
    token_bob = await _signup_login(client, sent_emails, "bob")
    await client.post("/account/v1/orgs", json={"org_id": "team-a"}, headers=_auth(token_alice))
    await client.post(
        "/account/v1/orgs/team-a/members", json={"user_id": "bob"}, headers=_auth(token_alice)
    )
    promote = await client.post(
        "/account/v1/orgs/team-a/members/bob/set-role",
        json={"role": "owner"},
        headers=_auth(token_alice),
    )
    assert promote.status_code == 200
    assert promote.json() == {"user_id": "bob", "role": "owner"}

    leave = await client.post("/account/v1/orgs/team-a/leave", headers=_auth(token_alice))
    assert leave.status_code == 204

    members = await client.get("/account/v1/orgs/team-a/members", headers=_auth(token_bob))
    assert members.json() == {"members": [{"user_id": "bob", "role": "owner"}]}


async def test_leave_non_member_is_404(client: AsyncClient, sent_emails):
    token_alice = await _signup_login(client, sent_emails, "alice")
    token_bob = await _signup_login(client, sent_emails, "bob")
    await client.post("/account/v1/orgs", json={"org_id": "team-a"}, headers=_auth(token_alice))
    response = await client.post("/account/v1/orgs/team-a/leave", headers=_auth(token_bob))
    assert response.status_code == 404


async def test_list_members_personal_org_owner_only(client: AsyncClient, sent_emails):
    token_alice = await _signup_login(client, sent_emails, "alice")
    token_bob = await _signup_login(client, sent_emails, "bob")

    own = await client.get("/account/v1/orgs/alice/members", headers=_auth(token_alice))
    assert own.status_code == 200
    assert own.json() == {"members": [{"user_id": "alice", "role": "owner"}]}

    other = await client.get("/account/v1/orgs/alice/members", headers=_auth(token_bob))
    assert other.status_code == 403


async def test_list_members_shared_org_requires_membership(client: AsyncClient, sent_emails):
    token_alice = await _signup_login(client, sent_emails, "alice")
    token_bob = await _signup_login(client, sent_emails, "bob")
    await client.post("/account/v1/orgs", json={"org_id": "team-a"}, headers=_auth(token_alice))

    non_member = await client.get("/account/v1/orgs/team-a/members", headers=_auth(token_bob))
    assert non_member.status_code == 403


async def test_list_orgs_and_me_show_personal_and_shared(client: AsyncClient, sent_emails):
    token_alice = await _signup_login(client, sent_emails, "alice")
    await client.post("/account/v1/orgs", json={"org_id": "team-a"}, headers=_auth(token_alice))

    orgs = await client.get("/account/v1/orgs", headers=_auth(token_alice))
    assert orgs.status_code == 200
    org_ids = {entry["org_id"]: entry for entry in orgs.json()["orgs"]}
    assert org_ids["alice"] == {"org_id": "alice", "kind": "personal", "role": "owner"}
    assert org_ids["team-a"] == {"org_id": "team-a", "kind": "shared", "role": "owner"}

    me = await client.get("/account/v1/me", headers=_auth(token_alice))
    assert me.status_code == 200
    me_body = me.json()
    assert me_body["id"] == "alice"
    assert {o["org_id"] for o in me_body["orgs"]} == {"alice", "team-a"}


async def test_org_endpoints_require_auth(client: AsyncClient):
    response = await client.get("/account/v1/orgs")
    assert response.status_code == 401
