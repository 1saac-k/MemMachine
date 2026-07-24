"""Load/save the local login credentials file (DESIGN.md §5, §9.1)."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import TypedDict

DEFAULT_CREDENTIALS_PATH = "~/.config/memmachine-account/credentials"
CREDENTIALS_PATH_ENV_VAR = "MEMMACHINE_ACCOUNT_CREDENTIALS_FILE"


class Credentials(TypedDict):
    """Shape of the on-disk credentials file."""

    base_url: str
    id: str
    token: str


def resolve_credentials_path(explicit_path: str | None = None) -> Path:
    """Resolve the credentials file path from an explicit arg, env var, or default."""
    raw_path = (
        explicit_path or os.environ.get(CREDENTIALS_PATH_ENV_VAR) or DEFAULT_CREDENTIALS_PATH
    )
    return Path(raw_path).expanduser()


def load_credentials(explicit_path: str | None = None) -> Credentials | None:
    """Load saved credentials, or None if not logged in."""
    path = resolve_credentials_path(explicit_path)
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def save_credentials(credentials: Credentials, explicit_path: str | None = None) -> None:
    """Save credentials, creating the parent directory and restricting file permissions.

    Stored as plain JSON (DESIGN.md §5: internal network, no encryption
    required) but still chmod 0600 as a free, low-cost hardening against
    other local accounts on the same machine.
    """
    path = resolve_credentials_path(explicit_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(credentials))
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def clear_credentials(explicit_path: str | None = None) -> None:
    """Delete the saved credentials file, if any."""
    path = resolve_credentials_path(explicit_path)
    path.unlink(missing_ok=True)
