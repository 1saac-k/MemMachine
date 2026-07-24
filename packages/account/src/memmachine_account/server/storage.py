"""SQLAlchemy models and async session/engine setup for the account SQLite store.

Mirrors the data model in packages/account/DESIGN.md §4. All identifier
columns (`id`, `org_id`) are natural keys (already-unique, API-facing
strings) rather than surrogate integer primary keys, since a surrogate key
would just duplicate the natural key without adding value here.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def as_aware_utc(value: datetime) -> datetime:
    """Reattach UTC tzinfo to a datetime read back from SQLite.

    SQLite (via aiosqlite) does not persist tzinfo even for
    `DateTime(timezone=True)` columns: values written as aware UTC come
    back naive. Callers that compare a DB-sourced datetime against
    `utcnow()` must pass it through this first, or the comparison raises
    `TypeError: can't compare offset-naive and offset-aware datetimes`.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class UserStatus(enum.StrEnum):
    """Lifecycle status of a User account (DESIGN.md §4)."""

    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    DEACTIVATED = "deactivated"
    LOCKED = "locked"


class OrgKind(enum.StrEnum):
    """Whether an Org is a user's personal org or a shared org (DESIGN.md §4)."""

    PERSONAL = "personal"
    SHARED = "shared"


class OrgRole(enum.StrEnum):
    """A user's role within a shared org's membership (DESIGN.md §4/§6)."""

    OWNER = "owner"
    MEMBER = "member"


class ChallengePurpose(enum.StrEnum):
    """What an EmailChallenge code was issued for (DESIGN.md §4/§5)."""

    SIGNUP_VERIFICATION = "signup_verification"
    PASSWORD_RESET = "password_reset"
    LOCKOUT_RESET = "lockout_reset"
    EMAIL_CHANGE = "email_change"


class Base(DeclarativeBase):
    """Declarative base for all account-store ORM models."""


class User(Base):
    """A registered account (DESIGN.md §4 User table)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    pending_email: Mapped[str | None] = mapped_column(String, default=None)
    password_hash: Mapped[str] = mapped_column(String)
    is_admin: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String, default=UserStatus.PENDING_VERIFICATION.value)
    personal_org_id: Mapped[str] = mapped_column(String, unique=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Org(Base):
    """An organization namespace mapped to a MemMachine org_id (DESIGN.md §4 Org table)."""

    __tablename__ = "orgs"

    org_id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String)
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrgMembership(Base):
    """A user's membership/role in a shared org (DESIGN.md §4 OrgMembership table)."""

    __tablename__ = "org_memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_org_membership"),)

    org_id: Mapped[str] = mapped_column(String, ForeignKey("orgs.org_id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String, default=OrgRole.MEMBER.value)


class Token(Base):
    """A bearer token issued at login (DESIGN.md §4 Token table)."""

    __tablename__ = "tokens"

    token_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    token_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class EmailChallenge(Base):
    """A pending email verification / reset / unlock / email-change code (DESIGN.md §4)."""

    __tablename__ = "email_challenges"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String)
    code_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class AuditLog(Base):
    """A single audited API call (DESIGN.md §4 AuditLog table)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user_id: Mapped[str | None] = mapped_column(String, default=None)
    method: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    org_id: Mapped[str | None] = mapped_column(String, default=None)
    project_id: Mapped[str | None] = mapped_column(String, default=None)
    status_code: Mapped[int] = mapped_column(Integer)


def create_engine(sqlite_path: str) -> AsyncEngine:
    """Create the async SQLAlchemy engine for the given SQLite file path."""
    return create_async_engine(f"sqlite+aiosqlite:///{sqlite_path}")


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to the given engine."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_models(engine: AsyncEngine) -> None:
    """Create all tables if they do not already exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield a session for use as a FastAPI dependency, committing on success."""
    async with session_factory() as session:
        yield session
