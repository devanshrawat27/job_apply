"""Session probe: only a 401 means the saved X login is dead."""

from __future__ import annotations

import httpx

from app.services import x_dm_api


class _FakeClient:
    def __init__(self, status_code: int | None) -> None:
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url: str):
        if self.status_code is None:
            raise httpx.ConnectError("network down")
        return httpx.Response(self.status_code, request=httpx.Request("GET", url))


def test_401_marks_the_session_expired(monkeypatch):
    monkeypatch.setattr(x_dm_api, "_client", lambda *a, **k: _FakeClient(401))
    ok, reason = x_dm_api.check_session({"auth_token": "a", "ct0": "b"})
    assert ok is False
    assert "expired" in reason


def test_200_keeps_the_session_connected(monkeypatch):
    monkeypatch.setattr(x_dm_api, "_client", lambda *a, **k: _FakeClient(200))
    assert x_dm_api.check_session({"auth_token": "a", "ct0": "b"}) == (True, "")


def test_rate_limit_and_network_errors_are_not_expiry(monkeypatch):
    monkeypatch.setattr(x_dm_api, "_client", lambda *a, **k: _FakeClient(429))
    assert x_dm_api.check_session({"auth_token": "a", "ct0": "b"})[0] is True
    monkeypatch.setattr(x_dm_api, "_client", lambda *a, **k: _FakeClient(None))
    assert x_dm_api.check_session({"auth_token": "a", "ct0": "b"})[0] is True
