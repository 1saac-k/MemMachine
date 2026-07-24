"""Audit log recording: request-state helpers + the middleware that writes rows.

Route handlers/dependencies call `mark_audit_user`/`mark_audit_org` to
attach who/what a request was about; `AuditLogMiddleware` reads that back
after the response is generated and writes one `AuditLog` row per request
(DESIGN.md §4 AuditLog, §15). A middleware (rather than writing inline in
every handler) is what lets this stay a single, un-skippable choke point.
"""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from memmachine_account.server.storage import AuditLog


def mark_audit_user(request: Request, user_id: str) -> None:
    """Record which account a request is about, for the audit log (§4)."""
    request.state.audit_user_id = user_id


def mark_audit_org(request: Request, org_id: str | None, project_id: str | None) -> None:
    """Record which org/project a proxied data request targeted, for the audit log (§4)."""
    request.state.audit_org_id = org_id
    request.state.audit_project_id = project_id


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Write one AuditLog row per request, in its own session/transaction."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Run the request, then record it regardless of outcome."""
        response = await call_next(request)

        session_factory = request.app.state.session_factory
        async with session_factory() as session:
            session.add(
                AuditLog(
                    user_id=getattr(request.state, "audit_user_id", None),
                    method=request.method,
                    path=request.url.path,
                    org_id=getattr(request.state, "audit_org_id", None),
                    project_id=getattr(request.state, "audit_project_id", None),
                    status_code=response.status_code,
                )
            )
            await session.commit()

        return response
