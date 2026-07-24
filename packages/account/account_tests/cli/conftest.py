"""Shared fixtures for CLI tests: a fake `requests.request` recording calls."""

from __future__ import annotations

import json as json_module
from dataclasses import dataclass, field
from typing import Any

import pytest

from memmachine_account.cli import client as client_module


@dataclass
class FakeResponse:
    status_code: int
    _body: Any = None
    content: bytes = b"{}"

    def json(self) -> Any:
        return self._body


@dataclass
class FakeRequests:
    """Records every call and returns whatever `responses` yields next (default: 200 {})."""

    calls: list[dict[str, Any]] = field(default_factory=list)
    responses: list[FakeResponse] = field(default_factory=list)

    def request(self, method: str, url: str, json: Any = None, headers: Any = None, timeout: Any = None) -> FakeResponse:
        self.calls.append({"method": method, "url": url, "json": json, "headers": headers})
        if self.responses:
            return self.responses.pop(0)
        return FakeResponse(status_code=200, _body={}, content=b"{}")

    def queue(self, status_code: int, body: Any) -> None:
        content = json_module.dumps(body).encode() if body is not None else b""
        self.responses.append(FakeResponse(status_code=status_code, _body=body, content=content))


@pytest.fixture
def fake_requests(monkeypatch: pytest.MonkeyPatch) -> FakeRequests:
    fake = FakeRequests()
    monkeypatch.setattr(client_module.requests, "request", fake.request)
    return fake
