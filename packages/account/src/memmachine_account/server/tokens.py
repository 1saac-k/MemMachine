"""Token issuance and validation (DESIGN.md §4 Token, §8.2, §15).

Validity requires both "not revoked" AND "owner status == active" so that
deactivating/locking a user immediately blocks their existing sessions
even though tokens never expire on their own.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memmachine_account.server.security import generate_bearer_token, hash_token
from memmachine_account.server.storage import Token, User, UserStatus


async def issue_token(session: AsyncSession, user: User) -> str:
    """Issue a new bearer token for a user, returning the raw token (shown once)."""
    raw_token = generate_bearer_token()
    session.add(Token(token_hash=hash_token(raw_token), user_id=user.id))
    await session.commit()
    return raw_token


async def get_user_for_token(session: AsyncSession, raw_token: str) -> User | None:
    """Resolve a raw bearer token to its owning User, or None if invalid.

    Invalid means: no such token, the token has been revoked, or the
    owning user's status is not `active` (§4).
    """
    token_hash = hash_token(raw_token)
    result = await session.execute(select(Token).where(Token.token_hash == token_hash))
    token = result.scalar_one_or_none()
    if token is None or token.revoked_at is not None:
        return None

    user = await session.get(User, token.user_id)
    if user is None or user.status != UserStatus.ACTIVE.value:
        return None

    token.last_used_at = datetime.now(UTC)
    await session.commit()
    return user


async def revoke_token_by_hash(session: AsyncSession, raw_token: str) -> bool:
    """Revoke the token matching the given raw token value. Returns whether one was found."""
    token_hash = hash_token(raw_token)
    result = await session.execute(select(Token).where(Token.token_hash == token_hash))
    token = result.scalar_one_or_none()
    if token is None or token.revoked_at is not None:
        return False
    token.revoked_at = datetime.now(UTC)
    await session.commit()
    return True
