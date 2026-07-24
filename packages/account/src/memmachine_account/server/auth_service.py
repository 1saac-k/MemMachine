"""Core auth business logic: signup, verification, login/lockout, resets, email change.

DESIGN.md §5 (flows) and §8.2 (endpoint contracts). Each public function
here maps 1:1 to an `/account/v1/*` route wired in `server/app.py`.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memmachine_account.server import security
from memmachine_account.server.config import AppConfig
from memmachine_account.server.errors import AccountError
from memmachine_account.server.mail import render_code_email, send_email
from memmachine_account.server.storage import (
    ChallengePurpose,
    EmailChallenge,
    Org,
    OrgKind,
    User,
    UserStatus,
    as_aware_utc,
    utcnow,
)
from memmachine_account.server.tokens import issue_token, revoke_token_by_hash


async def _require_user(session: AsyncSession, user_id: str) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise AccountError(404, "no such account")
    return user


async def _issue_challenge(
    session: AsyncSession, config: AppConfig, user: User, purpose: str
) -> None:
    code = security.generate_numeric_code(config.auth.email_code_length)
    expires_at = utcnow() + timedelta(minutes=config.auth.email_code_expiry_minutes)
    session.add(
        EmailChallenge(
            user_id=user.id,
            purpose=purpose,
            code_hash=security.hash_code(code),
            expires_at=expires_at,
        )
    )
    await session.commit()

    to_address = user.email
    if purpose == ChallengePurpose.EMAIL_CHANGE.value and user.pending_email:
        to_address = user.pending_email
    subject, body = render_code_email(
        purpose=purpose, code=code, expiry_minutes=config.auth.email_code_expiry_minutes
    )
    await send_email(config.smtp, to_address, subject, body)


async def _consume_challenge(
    session: AsyncSession, user: User, code: str, purpose: str
) -> None:
    result = await session.execute(
        select(EmailChallenge)
        .where(
            EmailChallenge.user_id == user.id,
            EmailChallenge.purpose == purpose,
            EmailChallenge.consumed_at.is_(None),
        )
        .order_by(EmailChallenge.created_at.desc())
    )
    challenge = result.scalars().first()
    if challenge is None:
        raise AccountError(400, "no pending code for this action")
    if as_aware_utc(challenge.expires_at) < utcnow():
        raise AccountError(400, "code has expired")
    if security.hash_code(code) != challenge.code_hash:
        raise AccountError(400, "code does not match")
    challenge.consumed_at = utcnow()
    await session.commit()


def _require_password_length(config: AppConfig, password: str) -> None:
    if len(password) < config.auth.password_min_length:
        raise AccountError(
            400, f"password must be at least {config.auth.password_min_length} characters"
        )


async def signup(session: AsyncSession, config: AppConfig, user_id: str, email: str, password: str) -> User:
    """Create a pending account + personal org, and send a verification code (DESIGN.md §5)."""
    if not security.is_valid_account_id(user_id):
        raise AccountError(400, "id must be letters/digits/-/., no leading/trailing/consecutive specials")
    _require_password_length(config, password)
    if not security.email_domain_allowed(email, config.auth.allowed_email_domains):
        raise AccountError(403, "email domain not allowed")

    if await session.get(User, user_id) is not None:
        raise AccountError(409, "id already exists")
    existing_email = await session.execute(select(User).where(User.email == email))
    if existing_email.scalar_one_or_none() is not None:
        raise AccountError(409, "email already in use")

    personal_org_id = security.personal_org_id_for(user_id)
    if await session.get(Org, personal_org_id) is not None:
        raise AccountError(409, "personal org_id collides with an existing org; choose a different id")

    is_admin = email.lower() in {seed.lower() for seed in config.auth.seed_admins}

    user = User(
        id=user_id,
        email=email,
        password_hash=security.hash_password(password),
        is_admin=is_admin,
        status=UserStatus.PENDING_VERIFICATION.value,
        personal_org_id=personal_org_id,
    )
    session.add(user)
    session.add(Org(org_id=personal_org_id, kind=OrgKind.PERSONAL.value, created_by=user_id))
    await session.commit()

    await _issue_challenge(session, config, user, ChallengePurpose.SIGNUP_VERIFICATION.value)
    return user


async def verify_email(session: AsyncSession, user_id: str, code: str) -> User:
    """Confirm a signup verification code and activate the account."""
    user = await _require_user(session, user_id)
    await _consume_challenge(session, user, code, ChallengePurpose.SIGNUP_VERIFICATION.value)
    user.status = UserStatus.ACTIVE.value
    await session.commit()
    return user


async def resend_code(session: AsyncSession, config: AppConfig, user_id: str) -> None:
    """Resend the code for whichever pending state the account is currently in."""
    user = await _require_user(session, user_id)
    if user.status == UserStatus.PENDING_VERIFICATION.value:
        purpose = ChallengePurpose.SIGNUP_VERIFICATION.value
    elif user.status == UserStatus.LOCKED.value:
        purpose = ChallengePurpose.LOCKOUT_RESET.value
    else:
        raise AccountError(409, "no pending verification or lockout to resend a code for")
    await _issue_challenge(session, config, user, purpose)


async def _register_failed_login(session: AsyncSession, config: AppConfig, user: User) -> bool:
    """Increment the failed-login counter, locking the account if the threshold is hit."""
    user.failed_login_count += 1
    locked_now = user.failed_login_count >= config.auth.failed_login_lockout_threshold
    if locked_now:
        user.status = UserStatus.LOCKED.value
        user.password_hash = security.random_unusable_password_hash()
    await session.commit()
    if locked_now:
        await _issue_challenge(session, config, user, ChallengePurpose.LOCKOUT_RESET.value)
    return locked_now


async def login(session: AsyncSession, config: AppConfig, user_id: str, password: str) -> tuple[User, str]:
    """Authenticate a user and issue a bearer token, applying lockout rules (DESIGN.md §5/§6)."""
    user = await session.get(User, user_id)
    if user is None:
        raise AccountError(401, "invalid id or password")

    if user.status == UserStatus.LOCKED.value:
        raise AccountError(423, "account is locked, check your email to unlock")
    if user.status == UserStatus.PENDING_VERIFICATION.value:
        raise AccountError(403, "email not verified yet")
    if user.status == UserStatus.DEACTIVATED.value:
        raise AccountError(403, "account is deactivated")

    if not security.verify_password(password, user.password_hash):
        locked_now = await _register_failed_login(session, config, user)
        if locked_now:
            raise AccountError(423, "account is locked, check your email to unlock")
        raise AccountError(401, "invalid id or password")

    user.failed_login_count = 0
    await session.commit()
    raw_token = await issue_token(session, user)
    return user, raw_token


async def logout(session: AsyncSession, raw_token: str) -> None:
    """Revoke the token used to authenticate the current request."""
    await revoke_token_by_hash(session, raw_token)


async def change_password(
    session: AsyncSession, config: AppConfig, user: User, current_password: str, new_password: str
) -> None:
    """Change the current user's password after verifying their current one."""
    if not security.verify_password(current_password, user.password_hash):
        raise AccountError(401, "current password is incorrect")
    _require_password_length(config, new_password)
    user.password_hash = security.hash_password(new_password)
    await session.commit()


async def request_password_reset(session: AsyncSession, config: AppConfig, email: str) -> None:
    """Send a password-reset code if the email belongs to an account (anti-enumeration: §8.1)."""
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is not None:
        await _issue_challenge(session, config, user, ChallengePurpose.PASSWORD_RESET.value)


async def confirm_password_reset(
    session: AsyncSession, config: AppConfig, user_id: str, code: str, new_password: str
) -> None:
    """Confirm a password-reset code and set a new password."""
    user = await _require_user(session, user_id)
    await _consume_challenge(session, user, code, ChallengePurpose.PASSWORD_RESET.value)
    _require_password_length(config, new_password)
    user.password_hash = security.hash_password(new_password)
    await session.commit()


async def unlock(
    session: AsyncSession, config: AppConfig, user_id: str, code: str, new_password: str
) -> User:
    """Confirm a lockout-reset code, set a new password, and reactivate the account."""
    user = await _require_user(session, user_id)
    if user.status != UserStatus.LOCKED.value:
        raise AccountError(409, "account is not locked")
    await _consume_challenge(session, user, code, ChallengePurpose.LOCKOUT_RESET.value)
    _require_password_length(config, new_password)
    user.password_hash = security.hash_password(new_password)
    user.status = UserStatus.ACTIVE.value
    user.failed_login_count = 0
    await session.commit()
    return user


async def request_email_change(
    session: AsyncSession, config: AppConfig, user: User, new_email: str
) -> None:
    """Start an email change: validate the new address and send it a confirmation code."""
    if not security.email_domain_allowed(new_email, config.auth.allowed_email_domains):
        raise AccountError(400, "email domain not allowed")
    result = await session.execute(select(User).where(User.email == new_email))
    other = result.scalar_one_or_none()
    if other is not None and other.id != user.id:
        raise AccountError(409, "email already in use by another account")
    user.pending_email = new_email
    await session.commit()
    await _issue_challenge(session, config, user, ChallengePurpose.EMAIL_CHANGE.value)


async def confirm_email_change(session: AsyncSession, user: User, code: str) -> str:
    """Confirm an email-change code, swapping `pending_email` into `email`."""
    await _consume_challenge(session, user, code, ChallengePurpose.EMAIL_CHANGE.value)
    if not user.pending_email:
        raise AccountError(409, "no pending email change")
    user.email = user.pending_email
    user.pending_email = None
    await session.commit()
    return user.email
