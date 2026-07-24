"""Shared fixtures for account server tests: app + client with mocked SMTP."""

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from memmachine_account.server import auth_service
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
