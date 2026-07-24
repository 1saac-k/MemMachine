"""Tests for the SQLite storage layer (schema creation and constraints)."""

from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from memmachine_account.server.storage import (
    AuditLog,
    EmailChallenge,
    Org,
    OrgMembership,
    Token,
    User,
    create_engine,
    create_session_factory,
    init_models,
    utcnow,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path):
    engine = create_engine(str(tmp_path / "account_test.db"))
    await init_models(engine)
    factory = create_session_factory(engine)
    yield factory
    await engine.dispose()


async def _make_user(session_factory, user_id: str = "alice") -> None:
    async with session_factory() as session:
        session.add(
            User(
                id=user_id,
                email=f"{user_id}@company.com",
                password_hash="hashed",
                personal_org_id=user_id,
            )
        )
        await session.commit()


async def test_init_models_creates_tables(session_factory):
    async with session_factory() as session:
        for model in (User, Org, OrgMembership, Token, EmailChallenge, AuditLog):
            result = await session.execute(model.__table__.select())
            assert result.all() == []


async def test_user_id_is_unique(session_factory):
    await _make_user(session_factory, "alice")
    async with session_factory() as session:
        session.add(
            User(
                id="alice",
                email="other@company.com",
                password_hash="hashed",
                personal_org_id="other",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_user_email_is_unique(session_factory):
    await _make_user(session_factory, "alice")
    async with session_factory() as session:
        session.add(
            User(
                id="bob",
                email="alice@company.com",
                password_hash="hashed",
                personal_org_id="bob",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_user_personal_org_id_is_unique(session_factory):
    await _make_user(session_factory, "alice")
    async with session_factory() as session:
        session.add(
            User(
                id="bob",
                email="bob@company.com",
                password_hash="hashed",
                personal_org_id="alice",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_org_membership_unique_constraint(session_factory):
    await _make_user(session_factory, "alice")
    async with session_factory() as session:
        session.add(Org(org_id="team-a", kind="shared", created_by="alice"))
        await session.commit()
        session.add(OrgMembership(org_id="team-a", user_id="alice", role="owner"))
        await session.commit()

        session.add(OrgMembership(org_id="team-a", user_id="alice", role="member"))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_token_hash_unique_and_defaults(session_factory):
    await _make_user(session_factory, "alice")
    async with session_factory() as session:
        token = Token(token_hash="hash-1", user_id="alice")
        session.add(token)
        await session.commit()
        assert token.token_id
        assert token.revoked_at is None
        assert token.last_used_at is None

        session.add(Token(token_hash="hash-1", user_id="alice"))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_email_challenge_roundtrip(session_factory):
    await _make_user(session_factory, "alice")
    async with session_factory() as session:
        challenge = EmailChallenge(
            user_id="alice",
            purpose="signup_verification",
            code_hash="code-hash",
            expires_at=utcnow(),
        )
        session.add(challenge)
        await session.commit()
        assert challenge.id
        assert challenge.consumed_at is None


async def test_audit_log_allows_null_user_and_org(session_factory):
    async with session_factory() as session:
        session.add(
            AuditLog(method="POST", path="/account/v1/login", status_code=401)
        )
        await session.commit()
        result = await session.execute(AuditLog.__table__.select())
        row = result.one()
        assert row.user_id is None
        assert row.org_id is None
        assert row.status_code == 401
