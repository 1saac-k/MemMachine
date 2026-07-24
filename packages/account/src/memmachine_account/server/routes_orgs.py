"""`/account/v1/orgs*` routes (DESIGN.md §8.2): create/list/members/roles/leave."""

from __future__ import annotations

from fastapi import APIRouter, Response

from memmachine_account.api.spec import (
    AddMemberRequest,
    CreateOrgRequest,
    MemberInfo,
    MemberListResponse,
    OrgInfo,
    OrgListResponse,
    SetRoleRequest,
)
from memmachine_account.server import org_service
from memmachine_account.server.deps import CurrentUserDep, SessionDep

router = APIRouter(prefix="/orgs", tags=["Orgs"])


@router.post("", status_code=201)
async def create_org(
    spec: CreateOrgRequest, user: CurrentUserDep, session: SessionDep
) -> OrgInfo:
    """Create a shared org; the caller becomes its owner."""
    org = await org_service.create_org(session, user, spec.org_id)
    return OrgInfo(org_id=org.org_id, kind=org.kind, role="owner")


@router.get("")
async def list_orgs(user: CurrentUserDep, session: SessionDep) -> OrgListResponse:
    """List every org (personal + shared) the caller belongs to."""
    memberships = await org_service.list_orgs_for_user(session, user)
    return OrgListResponse(
        orgs=[
            OrgInfo(
                org_id=m.org_id,
                kind="personal" if m.org_id == user.personal_org_id else "shared",
                role=m.role,
            )
            for m in memberships
        ]
    )


@router.get("/{org_id}/members")
async def list_members(org_id: str, user: CurrentUserDep, session: SessionDep) -> MemberListResponse:
    """List a shared org's members (or the sole owner of a personal org)."""
    members = await org_service.list_members(session, user, org_id)
    return MemberListResponse(
        members=[MemberInfo(user_id=m.user_id, role=m.role) for m in members]
    )


@router.post("/{org_id}/members", status_code=201)
async def add_member(
    org_id: str, spec: AddMemberRequest, user: CurrentUserDep, session: SessionDep
) -> MemberInfo:
    """Add an existing registered user to a shared org (owner only)."""
    membership = await org_service.add_member(session, user, org_id, spec.user_id, spec.role)
    return MemberInfo(user_id=membership.user_id, role=membership.role)


@router.delete("/{org_id}/members/{target_user_id}", status_code=204)
async def remove_member(
    org_id: str, target_user_id: str, user: CurrentUserDep, session: SessionDep
) -> Response:
    """Remove a member from a shared org (owner only, cannot remove the last owner)."""
    await org_service.remove_member(session, user, org_id, target_user_id)
    return Response(status_code=204)


@router.post("/{org_id}/members/{target_user_id}/set-role")
async def set_role(
    org_id: str,
    target_user_id: str,
    spec: SetRoleRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> MemberInfo:
    """Promote/demote a shared org member (owner only, cannot demote the last owner)."""
    membership = await org_service.set_role(session, user, org_id, target_user_id, spec.role)
    return MemberInfo(user_id=membership.user_id, role=membership.role)


@router.post("/{org_id}/leave", status_code=204)
async def leave_org(org_id: str, user: CurrentUserDep, session: SessionDep) -> Response:
    """Leave a shared org (cannot leave your own personal org or as the last owner)."""
    await org_service.leave_org(session, user, org_id)
    return Response(status_code=204)
