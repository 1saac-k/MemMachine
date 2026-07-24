"""MemMachine `/api/v2/*` reverse-proxy: allow-list enforcement + permission checks.

DESIGN.md §2.1 (exact allow/block list), §6.1 (reject the "universal"
default), §2.3 (`/projects/list` response filtering). Everything else in
§2.1's "v1 프록시 O" table is a straight org/project-membership-gated
passthrough.
"""

from __future__ import annotations

import json

import httpx
from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from memmachine_account.server.config import AppConfig
from memmachine_account.server.errors import AccountError
from memmachine_account.server.org_service import is_member_of_org
from memmachine_account.server.storage import User

# DESIGN.md §2.1 "v1 프록시 O": org_id/project_id are read directly from the
# request body for every one of these except LIST_PROJECTS_PATH, which
# instead needs its *response* filtered (§2.3) since MemMachine returns
# every project on the server with no org filter of its own.
LIST_PROJECTS_PATH = "/api/v2/projects/list"

ALLOWED_PATHS: frozenset[str] = frozenset(
    {
        "/api/v2/projects",
        "/api/v2/projects/get",
        LIST_PROJECTS_PATH,
        "/api/v2/projects/delete",
        "/api/v2/projects/episode_count/get",
        "/api/v2/memories",
        "/api/v2/memories/search",
        "/api/v2/memories/list",
        "/api/v2/memories/episodic/delete",
        "/api/v2/memory/episodic/config",
        "/api/v2/memory/episodic/config/get",
        "/api/v2/memory/episodic/short_term/config",
        "/api/v2/memory/episodic/short_term/config/get",
        "/api/v2/memory/episodic/long_term/config",
        "/api/v2/memory/episodic/long_term/config/get",
        "/api/v2/memories/semantic/set_type",
        "/api/v2/memories/semantic/set_type/list",
        "/api/v2/memories/semantic/set_id/get",
        "/api/v2/memories/semantic/set_id/list",
    }
)

# DESIGN.md §2.1 "v1 프록시 X": opaque-ID-addressed endpoints, blocked in v1
# because the request carries no org_id/project_id to authorize against.
# Not consulted at runtime (anything not in ALLOWED_PATHS is already
# rejected) - kept only so tests can assert each of these specifically
# stays blocked, matching the design doc line for line.
BLOCKED_PATHS: frozenset[str] = frozenset(
    {
        "/api/v2/memories/semantic/delete",
        "/api/v2/memories/semantic/feature",
        "/api/v2/memories/semantic/feature/get",
        "/api/v2/memories/semantic/feature/update",
        "/api/v2/memories/semantic/set_type/delete",
        "/api/v2/memories/semantic/set/configure",
        "/api/v2/memories/semantic/category/get",
        "/api/v2/memories/semantic/category",
        "/api/v2/memories/semantic/category/template",
        "/api/v2/memories/semantic/category/template/list",
        "/api/v2/memories/semantic/category/disable",
        "/api/v2/memories/semantic/category/set_ids/get",
        "/api/v2/memories/semantic/category/delete",
        "/api/v2/memories/semantic/category/tag",
        "/api/v2/memories/semantic/category/tag/delete",
    }
)

_UNIVERSAL_DEFAULT = "universal"


async def _read_json_body(request: Request) -> dict:
    body = await request.body()
    if not body:
        return {}
    try:
        parsed = await request.json()
    except ValueError as exc:
        raise AccountError(400, "request body must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise AccountError(400, "request body must be a JSON object")
    return parsed


def _require_explicit_org_and_project(body: dict) -> tuple[str, str]:
    org_id = body.get("org_id")
    project_id = body.get("project_id")
    if not org_id or not project_id or org_id == _UNIVERSAL_DEFAULT or project_id == _UNIVERSAL_DEFAULT:
        raise AccountError(400, "org_id and project_id must be explicitly set (no 'universal' default)")
    return org_id, project_id


async def handle_proxy_request(
    full_path: str,
    request: Request,
    user: User,
    session: AsyncSession,
    config: AppConfig,
) -> Response:
    """Authorize and forward one `/api/v2/*` request to MemMachine."""
    if full_path not in ALLOWED_PATHS:
        raise AccountError(404, "not found")

    body = await _read_json_body(request)

    if full_path == LIST_PROJECTS_PATH:
        upstream_response = await forward_to_memmachine(config, request.method, full_path, body)
        return await _filtered_projects_list_response(upstream_response, user, session)

    org_id, _project_id = _require_explicit_org_and_project(body)
    if not await is_member_of_org(session, user, org_id):
        raise AccountError(403, "not a member of this org")

    upstream_response = await forward_to_memmachine(config, request.method, full_path, body)
    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        media_type=upstream_response.headers.get("content-type"),
    )


async def forward_to_memmachine(config: AppConfig, method: str, path: str, body: dict) -> httpx.Response:
    """Make one HTTP call to the MemMachine upstream (also reused by server/admin_service.py)."""
    async with httpx.AsyncClient(
        base_url=config.memmachine_upstream.base_url,
        timeout=config.memmachine_upstream.timeout_seconds,
    ) as upstream:
        return await upstream.request(method, path, json=body or None)


async def _filtered_projects_list_response(
    upstream_response: httpx.Response, user: User, session: AsyncSession
) -> Response:
    if upstream_response.status_code != 200:
        return Response(
            content=upstream_response.content,
            status_code=upstream_response.status_code,
            media_type=upstream_response.headers.get("content-type"),
        )

    entries = upstream_response.json()
    visible = [
        entry
        for entry in entries
        if await is_member_of_org(session, user, entry.get("org_id", ""))
    ]
    return Response(content=json.dumps(visible).encode(), status_code=200, media_type="application/json")
