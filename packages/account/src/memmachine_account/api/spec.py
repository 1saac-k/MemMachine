"""Request/response pydantic models for `/account/v1/*` (DESIGN.md §8.2).

Named and shaped to mirror `memmachine_common.api.spec` conventions. Models
for endpoints not yet implemented land in the commit that implements them
(orgs in M4, admin in M6).
"""

from __future__ import annotations

from datetime import datetime

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


class TokenInfo(BaseModel):
    """A single token entry as shown by `GET /account/v1/tokens` (never the raw value)."""

    token_id: str
    created_at: datetime
    last_used_at: datetime | None


class TokenListResponse(BaseModel):
    """Response body for `GET /account/v1/tokens`."""

    tokens: list[TokenInfo]


class OrgInfo(BaseModel):
    """A single org entry as seen by one of its members."""

    org_id: str
    kind: str
    role: str


class OrgListResponse(BaseModel):
    """Response body for `GET /account/v1/orgs` and the `orgs` field of `GET /account/v1/me`."""

    orgs: list[OrgInfo]


class CreateOrgRequest(BaseModel):
    """Request body for `POST /account/v1/orgs`."""

    org_id: str


class MemberInfo(BaseModel):
    """A single member entry as shown by `GET /account/v1/orgs/{org_id}/members`."""

    user_id: str
    role: str


class MemberListResponse(BaseModel):
    """Response body for `GET /account/v1/orgs/{org_id}/members`."""

    members: list[MemberInfo]


class AddMemberRequest(BaseModel):
    """Request body for `POST /account/v1/orgs/{org_id}/members`."""

    user_id: str
    role: str = "member"


class SetRoleRequest(BaseModel):
    """Request body for `POST /account/v1/orgs/{org_id}/members/{user_id}/set-role`."""

    role: str


class MeResponse(BaseModel):
    """Response body for `GET /account/v1/me`."""

    id: str
    email: str
    is_admin: bool
    status: str
    created_at: datetime
    orgs: list[OrgInfo]


class AdminUserInfo(BaseModel):
    """A single user entry as shown by `GET /account/v1/admin/users`."""

    id: str
    email: str
    is_admin: bool
    status: str
    created_at: datetime


class AdminUserListResponse(BaseModel):
    """Response body for `GET /account/v1/admin/users`."""

    users: list[AdminUserInfo]


class DeactivateUserResponse(BaseModel):
    """Response body for `POST /account/v1/admin/users/{id}/deactivate`."""

    id: str
    status: str


class PurgeUserRequest(BaseModel):
    """Request body for `POST /account/v1/admin/users/{id}/purge`. `confirm_id` must equal `id`."""

    confirm_id: str


class PurgeUserResponse(BaseModel):
    """Response body for `POST /account/v1/admin/users/{id}/purge`."""

    id: str
    deleted_org_ids: list[str]


class RevokeTokensResponse(BaseModel):
    """Response body for `POST /account/v1/admin/users/{id}/revoke-tokens`."""

    id: str
    revoked_count: int


class SyncSeedAdminsResponse(BaseModel):
    """Response body for `POST /account/v1/admin/sync-seed-admins`."""

    promoted: list[str]
    demoted: list[str]


class AdminOrgInfo(BaseModel):
    """A single org entry as shown by `GET /account/v1/admin/orgs`."""

    org_id: str
    kind: str
    created_by: str
    member_count: int


class AdminOrgListResponse(BaseModel):
    """Response body for `GET /account/v1/admin/orgs`."""

    orgs: list[AdminOrgInfo]
