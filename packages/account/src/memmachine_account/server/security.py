"""Password hashing, token/code generation, and id/email format validation.

Password hashing uses argon2id (slow, tuned for low-entropy human secrets).
Tokens and email codes are high-entropy/short-lived respectively, so they
are hashed with sha256 for fast lookup rather than argon2 (DECISIONS.md).
"""

from __future__ import annotations

import hashlib
import secrets
import string
from itertools import pairwise

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_password_hasher = PasswordHasher()

_ID_ALLOWED_CHARS = set(string.ascii_letters + string.digits)
_ID_SPECIAL_CHARS = set("-.")  # NOT "_" - DESIGN.md §4: id must not allow "_" so that the
# "." -> "_" org_id derivation stays injective (no two distinct valid ids can collide).


def hash_password(password: str) -> str:
    """Hash a plaintext password with argon2id."""
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check a plaintext password against a stored argon2id hash."""
    try:
        return _password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def random_unusable_password_hash() -> str:
    """Hash a random, never-communicated password (used to lock out an account)."""
    return hash_password(secrets.token_urlsafe(32))


def is_valid_account_id(value: str) -> bool:
    """Validate an account id: letters/digits/-/., no leading/trailing/consecutive specials."""
    if not value:
        return False
    if not all(char in _ID_ALLOWED_CHARS or char in _ID_SPECIAL_CHARS for char in value):
        return False
    if value[0] in _ID_SPECIAL_CHARS or value[-1] in _ID_SPECIAL_CHARS:
        return False
    return not any(
        left in _ID_SPECIAL_CHARS and right in _ID_SPECIAL_CHARS
        for left, right in pairwise(value)
    )


def personal_org_id_for(user_id: str) -> str:
    """Derive a user's personal org_id from their account id (DESIGN.md §4/§5)."""
    return user_id.replace(".", "_")


def email_domain_allowed(email: str, allowed_domains: list[str]) -> bool:
    """Check whether an email's domain is in the configured allowlist (case-insensitive)."""
    if "@" not in email:
        return False
    domain = email.rsplit("@", 1)[-1].lower()
    return domain in {allowed.lower() for allowed in allowed_domains}


def generate_numeric_code(length: int) -> str:
    """Generate a random numeric verification/reset code of the given length."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


def hash_code(code: str) -> str:
    """Hash a short-lived numeric code for at-rest storage."""
    return hashlib.sha256(code.encode()).hexdigest()


def generate_bearer_token() -> str:
    """Generate a high-entropy bearer token for a login session."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash a bearer token for at-rest storage (sha256 is sufficient for high-entropy input)."""
    return hashlib.sha256(token.encode()).hexdigest()
