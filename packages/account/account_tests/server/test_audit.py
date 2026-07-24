"""Audit log + health check tests (DESIGN.md §14.1 "감사 로그", §13)."""

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from account_tests.server.conftest import extract_code
from memmachine_account.server.config import AppConfig
from memmachine_account.server.storage import (
    AuditLog,
    create_engine,
    create_session_factory,
)

pytestmark = pytest.mark.asyncio

SIGNUP_BODY = {"id": "alice", "email": "alice@company.com", "password": "correct-horse"}


async def _audit_rows(config: AppConfig) -> list[AuditLog]:
    engine = create_engine(config.storage.sqlite_path)
    factory = create_session_factory(engine)
    async with factory() as session:
        result = await session.execute(select(AuditLog).order_by(AuditLog.id))
        rows = list(result.scalars().all())
    await engine.dispose()
    return rows


async def test_health_check_unauthenticated(client: AsyncClient):
    response = await client.get("/account/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


async def test_health_check_not_audited_path_matches(client: AsyncClient, config: AppConfig):
    await client.get("/account/v1/health")
    rows = await _audit_rows(config)
    assert any(r.path == "/account/v1/health" and r.status_code == 200 for r in rows)


async def test_failed_login_is_audited_with_attempted_id(client: AsyncClient, config: AppConfig):
    await client.post("/account/v1/login", json={"id": "nobody", "password": "x"})
    rows = await _audit_rows(config)
    login_rows = [r for r in rows if r.path == "/account/v1/login"]
    assert len(login_rows) == 1
    assert login_rows[0].user_id == "nobody"
    assert login_rows[0].status_code == 401
    assert login_rows[0].org_id is None


async def test_successful_login_is_audited(client: AsyncClient, sent_emails, config: AppConfig):
    await client.post("/account/v1/signup", json=SIGNUP_BODY)
    code = extract_code(sent_emails[-1][2])
    await client.post("/account/v1/verify-email", json={"id": "alice", "code": code})
    await client.post(
        "/account/v1/login", json={"id": "alice", "password": SIGNUP_BODY["password"]}
    )

    rows = await _audit_rows(config)
    login_rows = [r for r in rows if r.path == "/account/v1/login" and r.status_code == 200]
    assert len(login_rows) == 1
    assert login_rows[0].user_id == "alice"


async def test_control_plane_call_has_no_org_project(client: AsyncClient, sent_emails, config: AppConfig):
    await client.post("/account/v1/signup", json=SIGNUP_BODY)
    code = extract_code(sent_emails[-1][2])
    await client.post("/account/v1/verify-email", json={"id": "alice", "code": code})
    login = await client.post(
        "/account/v1/login", json={"id": "alice", "password": SIGNUP_BODY["password"]}
    )
    token = login.json()["token"]
    await client.get("/account/v1/me", headers={"Authorization": f"Bearer {token}"})

    rows = await _audit_rows(config)
    me_rows = [r for r in rows if r.path == "/account/v1/me"]
    assert len(me_rows) == 1
    assert me_rows[0].user_id == "alice"
    assert me_rows[0].org_id is None
    assert me_rows[0].project_id is None


async def test_proxy_call_is_audited_with_org_and_project(
    client: AsyncClient, sent_emails, config: AppConfig, upstream
):
    await client.post("/account/v1/signup", json=SIGNUP_BODY)
    code = extract_code(sent_emails[-1][2])
    await client.post("/account/v1/verify-email", json={"id": "alice", "code": code})
    login = await client.post(
        "/account/v1/login", json={"id": "alice", "password": SIGNUP_BODY["password"]}
    )
    token = login.json()["token"]

    upstream["handler"] = lambda _request: httpx.Response(200, json={"ok": True})
    await client.post(
        "/api/v2/memories",
        json={"org_id": "alice", "project_id": "default", "messages": []},
        headers={"Authorization": f"Bearer {token}"},
    )

    rows = await _audit_rows(config)
    proxy_rows = [r for r in rows if r.path == "/api/v2/memories"]
    assert len(proxy_rows) == 1
    assert proxy_rows[0].org_id == "alice"
    assert proxy_rows[0].project_id == "default"
    assert proxy_rows[0].user_id == "alice"
    assert proxy_rows[0].status_code == 200


async def test_rejected_proxy_call_still_audited(
    client: AsyncClient, sent_emails, config: AppConfig, upstream
):
    await client.post("/account/v1/signup", json=SIGNUP_BODY)
    code = extract_code(sent_emails[-1][2])
    await client.post("/account/v1/verify-email", json={"id": "alice", "code": code})
    login = await client.post(
        "/account/v1/login", json={"id": "alice", "password": SIGNUP_BODY["password"]}
    )
    token = login.json()["token"]

    await client.post(
        "/api/v2/memories",
        json={"org_id": "someone-elses-org", "project_id": "default", "messages": []},
        headers={"Authorization": f"Bearer {token}"},
    )

    rows = await _audit_rows(config)
    proxy_rows = [r for r in rows if r.path == "/api/v2/memories"]
    assert len(proxy_rows) == 1
    assert proxy_rows[0].status_code == 403
    assert proxy_rows[0].org_id == "someone-elses-org"
