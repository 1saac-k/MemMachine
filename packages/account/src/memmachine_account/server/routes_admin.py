"""`/account/v1/admin/*` routes (DESIGN.md §8.2): user/org management only."""

from __future__ import annotations

from fastapi import APIRouter

from memmachine_account.api.spec import (
    AdminOrgListResponse,
    AdminUserInfo,
    AdminUserListResponse,
    DeactivateUserResponse,
    PurgeUserRequest,
    PurgeUserResponse,
    RevokeTokensResponse,
    SyncSeedAdminsResponse,
)
from memmachine_account.server import admin_service
from memmachine_account.server.deps import AdminUserDep, ConfigDep, SessionDep

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/users")
async def list_users(_: AdminUserDep, session: SessionDep) -> AdminUserListResponse:
    """List every registered user."""
    users = await admin_service.list_users(session)
    return AdminUserListResponse(
        users=[
            AdminUserInfo(
                id=u.id, email=u.email, is_admin=u.is_admin, status=u.status, created_at=u.created_at
            )
            for u in users
        ]
    )


@router.post("/users/{user_id}/deactivate")
async def deactivate_user(user_id: str, _: AdminUserDep, session: SessionDep) -> DeactivateUserResponse:
    """Deactivate a user (login/tokens blocked, data untouched)."""
    user = await admin_service.deactivate_user(session, user_id)
    return DeactivateUserResponse(id=user.id, status=user.status)


@router.post("/users/{user_id}/purge")
async def purge_user(
    user_id: str, spec: PurgeUserRequest, _: AdminUserDep, session: SessionDep, config: ConfigDep
) -> PurgeUserResponse:
    """Irreversibly delete a user, their personal org, and its MemMachine projects."""
    deleted_org_ids = await admin_service.purge_user(session, config, user_id, spec.confirm_id)
    return PurgeUserResponse(id=user_id, deleted_org_ids=deleted_org_ids)


@router.post("/users/{user_id}/revoke-tokens")
async def revoke_tokens(user_id: str, _: AdminUserDep, session: SessionDep) -> RevokeTokensResponse:
    """Revoke every token belonging to a user."""
    revoked_count = await admin_service.revoke_all_tokens(session, user_id)
    return RevokeTokensResponse(id=user_id, revoked_count=revoked_count)


@router.post("/sync-seed-admins")
async def sync_seed_admins(
    _: AdminUserDep, session: SessionDep, config: ConfigDep
) -> SyncSeedAdminsResponse:
    """Reconcile is_admin with the config seed-admin list (promotes and demotes)."""
    promoted, demoted = await admin_service.sync_seed_admins(session, config)
    return SyncSeedAdminsResponse(promoted=promoted, demoted=demoted)


@router.get("/orgs")
async def list_orgs(_: AdminUserDep, session: SessionDep) -> AdminOrgListResponse:
    """List every org on the server with its member count."""
    entries = await admin_service.list_orgs(session)
    return AdminOrgListResponse(orgs=entries)
