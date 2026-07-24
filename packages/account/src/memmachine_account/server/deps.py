"""Shared FastAPI dependencies: DB session, config, and current-user auth."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from memmachine_account.server.config import AppConfig
from memmachine_account.server.errors import AccountError
from memmachine_account.server.storage import User
from memmachine_account.server.tokens import get_user_for_token


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped DB session from the session factory on app state."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session


def get_config(request: Request) -> AppConfig:
    """Return the loaded AppConfig from app state."""
    return request.app.state.config


SessionDep = Annotated[AsyncSession, Depends(get_session)]
ConfigDep = Annotated[AppConfig, Depends(get_config)]


async def get_current_user_and_token(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> tuple[User, str]:
    """Resolve the authenticated user and raw bearer token from the Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise AccountError(401, "missing or malformed Authorization header")
    raw_token = authorization.removeprefix("Bearer ").strip()
    user = await get_user_for_token(session, raw_token)
    if user is None:
        raise AccountError(401, "invalid, revoked, or inactive token")
    return user, raw_token


async def get_current_user(
    user_and_token: Annotated[tuple[User, str], Depends(get_current_user_and_token)],
) -> User:
    """Resolve just the authenticated user (for handlers that don't need the raw token)."""
    return user_and_token[0]


CurrentUserDep = Annotated[User, Depends(get_current_user)]
CurrentUserAndTokenDep = Annotated[tuple[User, str], Depends(get_current_user_and_token)]


def require_admin(user: CurrentUserDep) -> User:
    """Require the current user to be a global admin (DESIGN.md §6)."""
    if not user.is_admin:
        raise AccountError(403, "admin privileges required")
    return user


AdminUserDep = Annotated[User, Depends(require_admin)]
