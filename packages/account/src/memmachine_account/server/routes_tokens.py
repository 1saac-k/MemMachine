"""`/account/v1/tokens` routes: list and revoke a user's own tokens (DESIGN.md §8.2)."""

from __future__ import annotations

from fastapi import APIRouter, Response

from memmachine_account.api.spec import TokenInfo, TokenListResponse
from memmachine_account.server import tokens as token_service
from memmachine_account.server.deps import CurrentUserDep, SessionDep
from memmachine_account.server.errors import AccountError

router = APIRouter(tags=["Tokens"])


@router.get("/tokens")
async def list_tokens(user: CurrentUserDep, session: SessionDep) -> TokenListResponse:
    """List the current user's tokens (never the raw token value)."""
    tokens = await token_service.list_tokens(session, user.id)
    return TokenListResponse(
        tokens=[
            TokenInfo(token_id=token.token_id, created_at=token.created_at, last_used_at=token.last_used_at)
            for token in tokens
        ]
    )


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_token(token_id: str, user: CurrentUserDep, session: SessionDep) -> Response:
    """Revoke one of the current user's own tokens."""
    revoked = await token_service.revoke_token_by_id(session, user.id, token_id)
    if not revoked:
        raise AccountError(404, "no such token")
    return Response(status_code=204)
