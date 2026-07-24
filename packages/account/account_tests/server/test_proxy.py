"""Gateway proxy tests (DESIGN.md §14.1 "권한 검사/프록시")."""

import json

import httpx
import pytest
from httpx import AsyncClient

from account_tests.server.conftest import extract_code
from memmachine_account.server.proxy import BLOCKED_PATHS

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
    return response.json()["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _echo_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=json.loads(request.content or b"{}"))


async def test_allowed_endpoint_forwards_for_member_org(client: AsyncClient, sent_emails, upstream):
    token = await _login(client, sent_emails)
    upstream["handler"] = _echo_handler

    response = await client.post(
        "/api/v2/memories",
        json={"org_id": "alice", "project_id": "default", "messages": [{"content": "hi"}]},
        headers=_auth(token),
    )
    assert response.status_code == 200
    assert response.json()["org_id"] == "alice"
    assert len(upstream["requests"]) == 1


async def test_producer_id_passed_through_unmodified(client: AsyncClient, sent_emails, upstream):
    token = await _login(client, sent_emails)
    upstream["handler"] = _echo_handler

    body = {
        "org_id": "alice",
        "project_id": "default",
        "messages": [{"content": "hi", "producer": "someone-else-entirely"}],
    }
    response = await client.post("/api/v2/memories", json=body, headers=_auth(token))
    assert response.json()["messages"][0]["producer"] == "someone-else-entirely"


async def test_non_member_org_rejected_before_forwarding(client: AsyncClient, sent_emails, upstream):
    token = await _login(client, sent_emails)
    upstream["handler"] = _echo_handler

    response = await client.post(
        "/api/v2/memories",
        json={"org_id": "someone-elses-org", "project_id": "default", "messages": []},
        headers=_auth(token),
    )
    assert response.status_code == 403
    assert upstream["requests"] == []


@pytest.mark.parametrize("bad_body", [{}, {"org_id": "alice"}, {"project_id": "default"}])
async def test_missing_org_or_project_rejected(client: AsyncClient, sent_emails, upstream, bad_body):
    token = await _login(client, sent_emails)
    upstream["handler"] = _echo_handler
    response = await client.post("/api/v2/memories", json=bad_body, headers=_auth(token))
    assert response.status_code == 400
    assert upstream["requests"] == []


async def test_universal_default_rejected(client: AsyncClient, sent_emails, upstream):
    token = await _login(client, sent_emails)
    upstream["handler"] = _echo_handler
    response = await client.post(
        "/api/v2/memories",
        json={"org_id": "universal", "project_id": "universal", "messages": []},
        headers=_auth(token),
    )
    assert response.status_code == 400
    assert upstream["requests"] == []


@pytest.mark.parametrize("blocked_path", sorted(BLOCKED_PATHS))
async def test_blocked_paths_are_404(client: AsyncClient, sent_emails, upstream, blocked_path: str):
    token = await _login(client, sent_emails)
    upstream["handler"] = _echo_handler
    response = await client.post(
        blocked_path, json={"org_id": "alice", "project_id": "default"}, headers=_auth(token)
    )
    assert response.status_code == 404
    assert upstream["requests"] == []


async def test_unknown_path_is_404(client: AsyncClient, sent_emails, upstream):
    token = await _login(client, sent_emails)
    response = await client.post("/api/v2/totally/made/up", json={}, headers=_auth(token))
    assert response.status_code == 404


async def test_proxy_requires_auth(client: AsyncClient, upstream):
    response = await client.post("/api/v2/memories", json={"org_id": "x", "project_id": "y"})
    assert response.status_code == 401
    assert upstream["requests"] == []


async def test_projects_list_filters_to_accessible_orgs_only(
    client: AsyncClient, sent_emails, upstream
):
    token_alice = await _login(client, sent_emails, "alice")
    await client.post("/account/v1/orgs", json={"org_id": "team-a"}, headers=_auth(token_alice))

    def all_projects(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"org_id": "alice", "project_id": "default"},
                {"org_id": "team-a", "project_id": "notes"},
                {"org_id": "someone-elses-org", "project_id": "secret"},
            ],
        )

    upstream["handler"] = all_projects
    response = await client.post(
        "/api/v2/projects/list", json={}, headers=_auth(token_alice)
    )
    assert response.status_code == 200
    org_ids = {entry["org_id"] for entry in response.json()}
    assert org_ids == {"alice", "team-a"}
