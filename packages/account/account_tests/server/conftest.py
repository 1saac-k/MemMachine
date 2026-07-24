"""Shared fixtures for account server tests: app + client with mocked SMTP/MemMachine."""

from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from memmachine_account.server import auth_service
from memmachine_account.server import proxy as proxy_module
from memmachine_account.server.app import create_app
from memmachine_account.server.config import (
    AppConfig,
    AuthSection,
    SmtpSection,
    StorageSection,
    UpstreamSection,
)


@pytest.fixture
def sent_emails(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    sent: list[tuple[str, str, str]] = []

    async def fake_send_email(_config: object, to_address: str, subject: str, body: str) -> None:
        sent.append((to_address, subject, body))

    monkeypatch.setattr(auth_service, "send_email", fake_send_email)
    return sent


@pytest.fixture
def config(tmp_path: Path, sent_emails: list[tuple[str, str, str]]) -> AppConfig:
    return AppConfig(
        memmachine_upstream=UpstreamSection(base_url="http://memmachine:8080"),
        storage=StorageSection(sqlite_path=str(tmp_path / "account.db")),
        auth=AuthSection(
            allowed_email_domains=["company.com"],
            seed_admins=["admin@company.com"],
        ),
        smtp=SmtpSection(
            host="smtp.company.com",
            username="notifications@company.com",
            password="secret",
            from_address="memmachine-noreply@company.com",
        ),
    )


@pytest_asyncio.fixture
async def client(config: AppConfig):
    app = create_app(config)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


def extract_code(body: str) -> str:
    """Pull the numeric code out of a rendered code email body (see server/mail.py)."""
    return body.split("Your code is: ")[1].split("\n", maxsplit=1)[0]


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Replace the proxy's httpx.AsyncClient with one backed by an in-process MockTransport.

    Tests set `upstream["handler"]` to a `(httpx.Request) -> httpx.Response`
    callable simulating MemMachine; `upstream["requests"]` records every
    request that actually reached the (mock) upstream, so tests can assert
    a request was rejected *before* being forwarded.
    """
    state: dict[str, object] = {
        "handler": lambda _request: httpx.Response(200, json={}),
        "requests": [],
    }

    def record_and_dispatch(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)  # type: ignore[attr-defined]
        return state["handler"](request)  # type: ignore[operator]

    real_async_client = httpx.AsyncClient  # capture before patching - see comment below

    def fake_async_client(*, base_url: str, timeout: float) -> httpx.AsyncClient:
        # `proxy_module.httpx` is the *same* module object as this file's
        # `httpx` import, so patching `.AsyncClient` on it patches the real
        # httpx module globally - referencing `httpx.AsyncClient` in here
        # would recurse into this fake. Use the pre-patch class instead.
        return real_async_client(
            transport=httpx.MockTransport(record_and_dispatch), base_url=base_url, timeout=timeout
        )

    monkeypatch.setattr(proxy_module.httpx, "AsyncClient", fake_async_client)
    return state
