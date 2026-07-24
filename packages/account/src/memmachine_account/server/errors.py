"""Structured error type mirroring MemMachine's RestError envelope (DESIGN.md §8.1)."""

from __future__ import annotations


class AccountError(Exception):
    """An error that should be rendered as `{"detail": {"code", "message", ...}}`."""

    def __init__(self, status_code: int, message: str) -> None:
        """Store the HTTP status code and human-readable message."""
        self.status_code = status_code
        self.message = message
        super().__init__(message)

    def to_detail(self) -> dict[str, str | int | None]:
        """Build the RestErrorModel-shaped `detail` payload (DESIGN.md §8.1)."""
        return {
            "code": self.status_code,
            "message": self.message,
            "exception": type(self).__name__,
            "internal_error": None,
            "trace": None,
        }
