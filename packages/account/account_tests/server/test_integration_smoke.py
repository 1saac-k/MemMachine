"""End-to-end smoke test against a *real* running MemMachine instance (DESIGN.md §14.2).

Skipped by default (root pyproject.toml: `addopts = ["-m", "not integration"]`,
same convention as the rest of this repo's `@pytest.mark.integration` tests).

To run this for real:
    1. Start MemMachine (e.g. `docker compose up -d postgres neo4j memmachine`
       from the repo root, or any other running instance).
    2. export MEMMACHINE_INTEGRATION_BASE_URL=http://localhost:8080
       (or wherever that instance is reachable from this machine).
    3. uv run --package memmachine-account pytest -m integration \
         packages/account/account_tests/server/test_integration_smoke.py

This was written but not executed in the session that authored it: the
sandbox has the `docker` CLI but no reachable daemon, so no MemMachine
instance could be started to point this at (DECISIONS.md, M9).
"""

import os

import pytest
from httpx import ASGITransport, AsyncClient

from account_tests.server.conftest import extract_code
from memmachine_account.server import auth_service
from memmachine_account.server.app import create_app
from memmachine_account.server.config import (
    AppConfig,
    AuthSection,
    SmtpSection,
    StorageSection,
    UpstreamSection,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

BASE_URL_ENV_VAR = "MEMMACHINE_INTEGRATION_BASE_URL"


@pytest.fixture
def real_memmachine_base_url() -> str:
    base_url = os.environ.get(BASE_URL_ENV_VAR)
    if not base_url:
        pytest.skip(f"set {BASE_URL_ENV_VAR} to a running MemMachine instance to run this test")
    return base_url


async def test_full_roundtrip_against_real_memmachine(
    tmp_path, monkeypatch: pytest.MonkeyPatch, real_memmachine_base_url: str
):
    """signup -> verify -> login -> org create -> project create -> memory add/search -> delete."""
    sent_emails: list[tuple[str, str, str]] = []

    async def fake_send_email(_config: object, to_address: str, subject: str, body: str) -> None:
        sent_emails.append((to_address, subject, body))

    monkeypatch.setattr(auth_service, "send_email", fake_send_email)

    config = AppConfig(
        memmachine_upstream=UpstreamSection(base_url=real_memmachine_base_url),
        storage=StorageSection(sqlite_path=str(tmp_path / "account.db")),
        auth=AuthSection(allowed_email_domains=["company.com"]),
        smtp=SmtpSection(
            host="unused", username="unused", password="unused", from_address="noreply@company.com"
        ),
    )
    app = create_app(config)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/account/v1/signup",
                json={"id": "smoketest", "email": "smoketest@company.com", "password": "correct-horse"},
            )
            code = extract_code(sent_emails[-1][2])
            await client.post(
                "/account/v1/verify-email", json={"id": "smoketest", "code": code}
            )
            login = await client.post(
                "/account/v1/login",
                json={"id": "smoketest", "password": "correct-horse"},
            )
            assert login.status_code == 200, login.text
            token = login.json()["token"]
            headers = {"Authorization": f"Bearer {token}"}

            create = await client.post(
                "/api/v2/projects",
                json={"org_id": "smoketest", "project_id": "smoke-project"},
                headers=headers,
            )
            assert create.status_code == 201, create.text

            add = await client.post(
                "/api/v2/memories",
                json={
                    "org_id": "smoketest",
                    "project_id": "smoke-project",
                    "messages": [{"content": "the smoke test ran"}],
                },
                headers=headers,
            )
            assert add.status_code == 200, add.text

            search = await client.post(
                "/api/v2/memories/search",
                json={"org_id": "smoketest", "project_id": "smoke-project", "query": "smoke test"},
                headers=headers,
            )
            assert search.status_code == 200, search.text

            delete = await client.post(
                "/api/v2/projects/delete",
                json={"org_id": "smoketest", "project_id": "smoke-project"},
                headers=headers,
            )
            assert delete.status_code == 204, delete.text
