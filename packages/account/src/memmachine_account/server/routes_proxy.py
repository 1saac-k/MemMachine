"""Catch-all `/api/v2/*` route that forwards to MemMachine (DESIGN.md §2, §2.1)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from memmachine_account.server.deps import ConfigDep, CurrentUserDep, SessionDep
from memmachine_account.server.proxy import handle_proxy_request

router = APIRouter(tags=["Proxy"])


@router.post("/api/v2/{path:path}")
async def proxy(
    path: str, request: Request, user: CurrentUserDep, session: SessionDep, config: ConfigDep
) -> Response:
    """Authorize and forward an `/api/v2/*` request to the MemMachine upstream."""
    return await handle_proxy_request(f"/api/v2/{path}", request, user, session, config)
