"""Admin business logic (DESIGN.md §6, §7, §8.2): user/org management only.

Deliberately has nothing to do with `/api/v2/*` data access - an admin
with no org membership of their own still cannot read anyone's memories
(DESIGN.md §6: "admin 권한은 계정/org 관리에 한정된다").
"""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from memmachine_account.api.spec import AdminOrgInfo
from memmachine_account.server.config import AppConfig
from memmachine_account.server.errors import AccountError
from memmachine_account.server.proxy import forward_to_memmachine
from memmachine_account.server.storage import (
    EmailChallenge,
    Org,
    OrgKind,
    OrgMembership,
    Token,
    User,
    UserStatus,
    utcnow,
)


async def _get_user_or_404(session: AsyncSession, user_id: str) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise AccountError(404, "no such user")
    return user


async def list_users(session: AsyncSession) -> list[User]:
    """List every registered user, oldest first."""
    result = await session.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())


async def deactivate_user(session: AsyncSession, user_id: str) -> User:
    """Deactivate a user: blocks login/tokens, leaves their data untouched (DESIGN.md §7)."""
    user = await _get_user_or_404(session, user_id)
    user.status = UserStatus.DEACTIVATED.value
    await session.commit()
    return user


async def purge_user(
    session: AsyncSession, config: AppConfig, user_id: str, confirm_id: str
) -> list[str]:
    """Irreversibly delete a user: their MemMachine projects, personal org, and account row.

    Requires `confirm_id == user_id` as a second, server-side check on top
    of whatever the CLI's own re-type confirmation already did (DESIGN.md
    §9: unlike `project delete`, this endpoint is ours to add a field to).
    """
    user = await _get_user_or_404(session, user_id)
    if confirm_id != user_id:
        raise AccountError(400, "confirm_id does not match id")

    list_response = await forward_to_memmachine(config, "POST", "/api/v2/projects/list", {})
    all_projects = list_response.json() if list_response.status_code == 200 else []
    own_projects = [p for p in all_projects if p.get("org_id") == user.personal_org_id]
    for project in own_projects:
        await forward_to_memmachine(
            config,
            "POST",
            "/api/v2/projects/delete",
            {"org_id": project["org_id"], "project_id": project["project_id"]},
        )
    deleted_org_ids = [user.personal_org_id] if own_projects else []

    await session.execute(delete(Token).where(Token.user_id == user_id))
    await session.execute(delete(EmailChallenge).where(EmailChallenge.user_id == user_id))
    personal_org = await session.get(Org, user.personal_org_id)
    if personal_org is not None:
        await session.delete(personal_org)
    await session.delete(user)
    await session.commit()
    return deleted_org_ids


async def revoke_all_tokens(session: AsyncSession, user_id: str) -> int:
    """Revoke every unrevoked token for a user (admin incident-response action)."""
    await _get_user_or_404(session, user_id)
    result = await session.execute(
        select(Token).where(Token.user_id == user_id, Token.revoked_at.is_(None))
    )
    tokens = list(result.scalars().all())
    now = utcnow()
    for token in tokens:
        token.revoked_at = now
    await session.commit()
    return len(tokens)


async def sync_seed_admins(
    session: AsyncSession, config: AppConfig
) -> tuple[list[str], list[str]]:
    """Reconcile `is_admin` with the config seed-admin list, promoting and demoting as needed.

    Refuses (409) if the sync would leave zero admins (DESIGN.md §5).
    """
    seed_emails = {email.lower() for email in config.auth.seed_admins}
    users = list((await session.execute(select(User))).scalars().all())

    promoted: list[str] = []
    demoted: list[str] = []
    for user in users:
        should_be_admin = user.email.lower() in seed_emails
        if should_be_admin and not user.is_admin:
            user.is_admin = True
            promoted.append(user.id)
        elif not should_be_admin and user.is_admin:
            user.is_admin = False
            demoted.append(user.id)

    if (promoted or demoted) and not any(user.is_admin for user in users):
        raise AccountError(409, "this sync would leave zero admins")

    await session.commit()
    return promoted, demoted


async def list_orgs(session: AsyncSession) -> list[AdminOrgInfo]:
    """List every org with its member count (personal orgs always count as 1)."""
    orgs = list((await session.execute(select(Org))).scalars().all())
    entries: list[AdminOrgInfo] = []
    for org in orgs:
        if org.kind == OrgKind.PERSONAL.value:
            member_count = 1
        else:
            count_result = await session.execute(
                select(func.count()).where(OrgMembership.org_id == org.org_id)
            )
            member_count = count_result.scalar_one()
        entries.append(
            AdminOrgInfo(
                org_id=org.org_id,
                kind=org.kind,
                created_by=org.created_by,
                member_count=member_count,
            )
        )
    return entries
