"""`/account/v1/*` auth routes (DESIGN.md §8.2): signup through email change."""

from __future__ import annotations

from fastapi import APIRouter, Response

from memmachine_account.api.spec import (
    ChangeEmailConfirmRequest,
    ChangeEmailRequestRequest,
    ChangeEmailResponse,
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    LoginUser,
    MeResponse,
    MessageResponse,
    OrgInfo,
    ResendCodeRequest,
    ResetPasswordConfirmRequest,
    ResetPasswordRequestRequest,
    SignupRequest,
    SignupResponse,
    StatusResponse,
    UnlockRequest,
    VerifyEmailRequest,
)
from memmachine_account.server import auth_service, org_service
from memmachine_account.server.deps import (
    ConfigDep,
    CurrentUserAndTokenDep,
    CurrentUserDep,
    SessionDep,
)

router = APIRouter(tags=["Auth"])


@router.post("/signup", status_code=201)
async def signup(spec: SignupRequest, session: SessionDep, config: ConfigDep) -> SignupResponse:
    """Create a pending account and send a signup verification code."""
    user = await auth_service.signup(session, config, spec.id, spec.email, spec.password)
    return SignupResponse(
        id=user.id, email=user.email, status=user.status, personal_org_id=user.personal_org_id
    )


@router.post("/verify-email")
async def verify_email(spec: VerifyEmailRequest, session: SessionDep) -> StatusResponse:
    """Confirm a signup verification code."""
    user = await auth_service.verify_email(session, spec.id, spec.code)
    return StatusResponse(status=user.status)


@router.post("/resend-code", status_code=202)
async def resend_code(spec: ResendCodeRequest, session: SessionDep, config: ConfigDep) -> MessageResponse:
    """Resend a signup-verification or lockout-reset code."""
    await auth_service.resend_code(session, config, spec.id)
    return MessageResponse(message="a new code has been sent")


@router.post("/login")
async def login(spec: LoginRequest, session: SessionDep, config: ConfigDep) -> LoginResponse:
    """Authenticate and issue a bearer token."""
    user, raw_token = await auth_service.login(session, config, spec.id, spec.password)
    return LoginResponse(
        token=raw_token,
        user=LoginUser(id=user.id, email=user.email, is_admin=user.is_admin, status=user.status),
    )


@router.post("/logout", status_code=204)
async def logout(user_and_token: CurrentUserAndTokenDep, session: SessionDep) -> Response:
    """Revoke the token used to authenticate this request."""
    _, raw_token = user_and_token
    await auth_service.logout(session, raw_token)
    return Response(status_code=204)


@router.post("/reset-password/request", status_code=202)
async def reset_password_request(
    spec: ResetPasswordRequestRequest, session: SessionDep, config: ConfigDep
) -> MessageResponse:
    """Send a password-reset code if the email belongs to an account (always the same response)."""
    await auth_service.request_password_reset(session, config, spec.email)
    return MessageResponse(message="if that email is registered, a reset code has been sent")


@router.post("/reset-password/confirm")
async def reset_password_confirm(
    spec: ResetPasswordConfirmRequest, session: SessionDep, config: ConfigDep
) -> MessageResponse:
    """Confirm a password-reset code and set a new password."""
    await auth_service.confirm_password_reset(session, config, spec.id, spec.code, spec.new_password)
    return MessageResponse(message="password has been reset")


@router.post("/unlock")
async def unlock(spec: UnlockRequest, session: SessionDep, config: ConfigDep) -> StatusResponse:
    """Confirm a lockout-reset code, set a new password, and reactivate the account."""
    user = await auth_service.unlock(session, config, spec.id, spec.code, spec.new_password)
    return StatusResponse(status=user.status)


@router.post("/change-password")
async def change_password(
    spec: ChangePasswordRequest, user: CurrentUserDep, session: SessionDep, config: ConfigDep
) -> MessageResponse:
    """Change the current user's password."""
    await auth_service.change_password(session, config, user, spec.current_password, spec.new_password)
    return MessageResponse(message="password changed")


@router.post("/change-email/request", status_code=202)
async def change_email_request(
    spec: ChangeEmailRequestRequest, user: CurrentUserDep, session: SessionDep, config: ConfigDep
) -> MessageResponse:
    """Start an email change, sending a confirmation code to the new address."""
    await auth_service.request_email_change(session, config, user, spec.new_email)
    return MessageResponse(message="a confirmation code has been sent to the new address")


@router.post("/change-email/confirm")
async def change_email_confirm(
    spec: ChangeEmailConfirmRequest, user: CurrentUserDep, session: SessionDep
) -> ChangeEmailResponse:
    """Confirm an email change."""
    new_email = await auth_service.confirm_email_change(session, user, spec.code)
    return ChangeEmailResponse(email=new_email)


@router.get("/me")
async def me(user: CurrentUserDep, session: SessionDep) -> MeResponse:
    """Return the current user's info and org memberships."""
    memberships = await org_service.list_orgs_for_user(session, user)
    return MeResponse(
        id=user.id,
        email=user.email,
        is_admin=user.is_admin,
        status=user.status,
        created_at=user.created_at,
        orgs=[
            OrgInfo(
                org_id=m.org_id,
                kind="personal" if m.org_id == user.personal_org_id else "shared",
                role=m.role,
            )
            for m in memberships
        ],
    )
