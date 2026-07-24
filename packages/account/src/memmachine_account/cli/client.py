"""Thin HTTP client for the memmachine-account gateway (DESIGN.md §9)."""

from __future__ import annotations

import requests
from pydantic import JsonValue


class AccountCliError(Exception):
    """A gateway error, with a message extracted from its RestError-style body."""


class AccountClient:
    """Small `requests`-based wrapper around the gateway's REST API."""

    def __init__(self, base_url: str, token: str | None = None, timeout: float = 30) -> None:
        """Store the gateway base URL, optional bearer token, and request timeout."""
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, method: str, path: str, json_body: dict[str, JsonValue] | None = None) -> JsonValue:
        """Make one request and return the parsed JSON body, raising on non-2xx."""
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        response = requests.request(
            method, f"{self.base_url}{path}", json=json_body, headers=headers, timeout=self.timeout
        )
        if response.status_code >= 400:
            raise AccountCliError(_extract_message(response))
        if not response.content:
            return None
        return response.json()


def _extract_message(response: requests.Response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(detail, dict) and "message" in detail:
        return str(detail["message"])
    if isinstance(detail, str):
        return detail
    return f"HTTP {response.status_code}"
