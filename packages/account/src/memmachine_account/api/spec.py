"""Request/response pydantic models for `/account/v1/*` (DESIGN.md §8.2).

Named and shaped to mirror `memmachine_common.api.spec` conventions. Models
for endpoints not yet implemented land in the commit that implements them
(orgs/tokens in M3-M4, admin in M6).
"""

from __future__ import annotations

from pydantic import BaseModel


class MessageResponse(BaseModel):
    """Generic acknowledgement response, e.g. `{"message": "..."}`."""

    message: str


class SignupRequest(BaseModel):
    """Request body for `POST /account/v1/signup`."""

    id: str
    email: str
    password: str


class SignupResponse(BaseModel):
    """Response body for `POST /account/v1/signup`."""

    id: str
    email: str
    status: str
    personal_org_id: str


class VerifyEmailRequest(BaseModel):
    """Request body for `POST /account/v1/verify-email`."""

    id: str
    code: str


class StatusResponse(BaseModel):
    """Response body carrying just the account's current status."""

    status: str


class ResendCodeRequest(BaseModel):
    """Request body for `POST /account/v1/resend-code`."""

    id: str


class LoginRequest(BaseModel):
    """Request body for `POST /account/v1/login`."""

    id: str
    password: str


class LoginUser(BaseModel):
    """The `user` object embedded in a login response."""

    id: str
    email: str
    is_admin: bool
    status: str


class LoginResponse(BaseModel):
    """Response body for `POST /account/v1/login`. `token` is shown only here."""

    token: str
    user: LoginUser


class ChangePasswordRequest(BaseModel):
    """Request body for `POST /account/v1/change-password`."""

    current_password: str
    new_password: str


class ResetPasswordRequestRequest(BaseModel):
    """Request body for `POST /account/v1/reset-password/request`."""

    email: str


class ResetPasswordConfirmRequest(BaseModel):
    """Request body for `POST /account/v1/reset-password/confirm`."""

    id: str
    code: str
    new_password: str


class UnlockRequest(BaseModel):
    """Request body for `POST /account/v1/unlock`."""

    id: str
    code: str
    new_password: str


class ChangeEmailRequestRequest(BaseModel):
    """Request body for `POST /account/v1/change-email/request`."""

    new_email: str


class ChangeEmailConfirmRequest(BaseModel):
    """Request body for `POST /account/v1/change-email/confirm`."""

    code: str


class ChangeEmailResponse(BaseModel):
    """Response body for `POST /account/v1/change-email/confirm`."""

    email: str
