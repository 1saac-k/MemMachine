"""Org/membership business logic (DESIGN.md §4, §6): create/list/members/roles/leave.

Personal orgs are single-owner and support no membership operations at
all (add/remove/set-role/leave all reject with 400). Shared orgs enforce
"at least one owner" on every operation that could otherwise remove the
last one (remove-member, set-role demotion, leave).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from memmachine_account.server import security
from memmachine_account.server.errors import AccountError
from memmachine_account.server.storage import Org, OrgKind, OrgMembership, OrgRole, User


async def create_org(session: AsyncSession, user: User, org_id: str) -> Org:
    """Create a new shared org; the creator becomes its sole owner."""
    if not security.is_valid_org_id(org_id):
        raise AccountError(400, "org_id must be lowercase letters/digits/-/_, no leading/trailing/consecutive specials")
    if await session.get(Org, org_id) is not None:
        raise AccountError(409, "org_id already exists")

    org = Org(org_id=org_id, kind=OrgKind.SHARED.value, created_by=user.id)
    session.add(org)
    session.add(OrgMembership(org_id=org_id, user_id=user.id, role=OrgRole.OWNER.value))
    await session.commit()
    return org


async def _get_org_or_404(session: AsyncSession, org_id: str) -> Org:
    org = await session.get(Org, org_id)
    if org is None:
        raise AccountError(404, "no such org")
    return org


async def _get_membership(session: AsyncSession, org_id: str, user_id: str) -> OrgMembership | None:
    return await session.get(OrgMembership, {"org_id": org_id, "user_id": user_id})


async def _require_owner(session: AsyncSession, org_id: str, user_id: str) -> None:
    membership = await _get_membership(session, org_id, user_id)
    if membership is None or membership.role != OrgRole.OWNER.value:
        raise AccountError(403, "only an org owner can do this")


async def _require_member(session: AsyncSession, org_id: str, user_id: str) -> OrgMembership:
    membership = await _get_membership(session, org_id, user_id)
    if membership is None:
        raise AccountError(403, "not a member of this org")
    return membership


async def _owner_count(session: AsyncSession, org_id: str) -> int:
    result = await session.execute(
        select(func.count()).where(
            OrgMembership.org_id == org_id, OrgMembership.role == OrgRole.OWNER.value
        )
    )
    return result.scalar_one()


async def list_orgs_for_user(session: AsyncSession, user: User) -> list[OrgMembership]:
    """List every org a user belongs to: their personal org plus any shared memberships."""
    memberships: list[OrgMembership] = [
        OrgMembership(org_id=user.personal_org_id, user_id=user.id, role=OrgRole.OWNER.value)
    ]
    result = await session.execute(
        select(OrgMembership).where(OrgMembership.user_id == user.id)
    )
    memberships.extend(result.scalars().all())
    return memberships


async def _org_kind(session: AsyncSession, org_id: str) -> str:
    org = await _get_org_or_404(session, org_id)
    return org.kind


async def add_member(
    session: AsyncSession, requester: User, org_id: str, target_user_id: str, role: str
) -> OrgMembership:
    """Add an existing registered user as a member (or owner) of a shared org."""
    if await _org_kind(session, org_id) == OrgKind.PERSONAL.value:
        raise AccountError(400, "personal orgs do not support membership management")
    await _require_owner(session, org_id, requester.id)

    if await session.get(User, target_user_id) is None:
        raise AccountError(404, "no such user")
    if await _get_membership(session, org_id, target_user_id) is not None:
        raise AccountError(409, "user is already a member")

    if role not in (OrgRole.OWNER.value, OrgRole.MEMBER.value):
        raise AccountError(400, "role must be 'owner' or 'member'")

    membership = OrgMembership(org_id=org_id, user_id=target_user_id, role=role)
    session.add(membership)
    await session.commit()
    return membership


async def remove_member(
    session: AsyncSession, requester: User, org_id: str, target_user_id: str
) -> None:
    """Remove a member from a shared org, refusing to remove the last owner."""
    if await _org_kind(session, org_id) == OrgKind.PERSONAL.value:
        raise AccountError(400, "personal orgs do not support membership management")
    await _require_owner(session, org_id, requester.id)

    target = await _get_membership(session, org_id, target_user_id)
    if target is None:
        raise AccountError(404, "user is not a member of this org")

    if target.role == OrgRole.OWNER.value and await _owner_count(session, org_id) <= 1:
        raise AccountError(409, "cannot remove the last owner of an org")

    await session.delete(target)
    await session.commit()


async def set_role(
    session: AsyncSession, requester: User, org_id: str, target_user_id: str, new_role: str
) -> OrgMembership:
    """Promote/demote a shared org member, refusing to demote the last owner."""
    if await _org_kind(session, org_id) == OrgKind.PERSONAL.value:
        raise AccountError(400, "personal orgs do not support membership management")
    await _require_owner(session, org_id, requester.id)

    if new_role not in (OrgRole.OWNER.value, OrgRole.MEMBER.value):
        raise AccountError(400, "role must be 'owner' or 'member'")

    target = await _get_membership(session, org_id, target_user_id)
    if target is None:
        raise AccountError(404, "user is not a member of this org")

    if (
        target.role == OrgRole.OWNER.value
        and new_role != OrgRole.OWNER.value
        and await _owner_count(session, org_id) <= 1
    ):
        raise AccountError(409, "cannot demote the last owner of an org")

    target.role = new_role
    await session.commit()
    return target


async def leave_org(session: AsyncSession, user: User, org_id: str) -> None:
    """Remove the current user from a shared org, refusing if they are the last owner.

    Unlike `list_members`, "not a member" here is a 404 (nothing to leave),
    not a 403 (DESIGN.md §8.2) - the two operations disagree on purpose.
    """
    if await _org_kind(session, org_id) == OrgKind.PERSONAL.value:
        raise AccountError(400, "you cannot leave your own personal org")

    membership = await _get_membership(session, org_id, user.id)
    if membership is None:
        raise AccountError(404, "you are not a member of this org")
    if membership.role == OrgRole.OWNER.value and await _owner_count(session, org_id) <= 1:
        raise AccountError(409, "cannot leave: you are the last owner of this org")

    await session.delete(membership)
    await session.commit()


async def list_members(session: AsyncSession, requester: User, org_id: str) -> list[OrgMembership]:
    """List a shared org's members, or the sole owner of a personal org."""
    org = await _get_org_or_404(session, org_id)
    if org.kind == OrgKind.PERSONAL.value:
        if requester.id != org.created_by:
            raise AccountError(403, "not a member of this org")
        return [OrgMembership(org_id=org_id, user_id=org.created_by, role=OrgRole.OWNER.value)]

    await _require_member(session, org_id, requester.id)
    result = await session.execute(select(OrgMembership).where(OrgMembership.org_id == org_id))
    return list(result.scalars().all())
