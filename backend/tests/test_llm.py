"""Key/model rotation and cooldown behaviour of the LLM client."""

from __future__ import annotations

import time

import pytest

import app.llm as llm


@pytest.fixture(autouse=True)
def _reset():
    llm.reset_cooldowns()
    yield
    llm.reset_cooldowns()


def _configure(monkeypatch, keys=("k1", "k2", "k3"), models=("m1", "m2")):
    monkeypatch.setattr(llm, "_keys", lambda: list(keys))
    monkeypatch.setattr(llm, "_models", lambda: list(models))


def test_quota_key_is_skipped_and_next_key_used(monkeypatch):
    _configure(monkeypatch)
    calls: list[int] = []
    index = {"value": 0}

    def fake_call(url, headers, payload):
        current = index["value"]
        index["value"] += 1
        calls.append(current)
        if current == 0:
            return "next_key", "HTTP 429 quota", 429
        return "ok", {"reply": "hi"}, 200

    monkeypatch.setattr(llm, "_call", fake_call)

    result = llm.complete_json("sys", "user")

    assert result == {"reply": "hi"}
    assert calls[:2] == [0, 1]
    assert llm._key_cooldown[0] > time.monotonic()
    assert 1 not in llm._key_cooldown


def test_all_keys_cooling_fails_fast(monkeypatch):
    _configure(monkeypatch)
    calls: list[int] = []

    def fake_call(url, headers, payload):
        calls.append(len(calls))
        return "next_key", "HTTP 429 quota", 429

    monkeypatch.setattr(llm, "_call", fake_call)

    with pytest.raises(llm.LLMUnavailable):
        llm.complete_json("sys", "user")

    assert len(calls) == 3
    assert all(llm._cooling(llm._key_cooldown, i) for i in range(3))


def test_overloaded_model_is_cooled_and_skipped_next_time(monkeypatch):
    _configure(monkeypatch)
    models_called: list[str] = []

    def fake_call(url, headers, payload):
        models_called.append(payload["model"])
        if payload["model"] == "m1":
            return "next_model", "HTTP 503 high demand", 503
        return "ok", {"ok": True}, 200

    monkeypatch.setattr(llm, "_call", fake_call)

    assert llm.complete_json("sys", "user") == {"ok": True}
    assert models_called[:2] == ["m1", "m2"]
    assert llm._cooling(llm._model_cooldown, "m1")

    models_called.clear()
    assert llm.complete_json("sys", "user") == {"ok": True}
    assert models_called == ["m2"]  # m1 is on cooldown now


def test_cooling_key_is_not_called(monkeypatch):
    _configure(monkeypatch)
    llm._key_cooldown[0] = time.monotonic() + 60
    used: list[int] = []

    def fake_call(url, headers, payload):
        used.append(1)
        return "ok", {"ok": True}, 200

    monkeypatch.setattr(llm, "_call", fake_call)

    assert llm.complete_json("sys", "user") == {"ok": True}
    assert used == [1]


def test_success_advances_the_preferred_key(monkeypatch):
    _configure(monkeypatch)

    def fake_call(url, headers, payload):
        return "ok", {"ok": True}, 200

    monkeypatch.setattr(llm, "_call", fake_call)
    llm.reset_cooldowns()

    llm.complete_json("sys", "user")
    first = llm._preferred_key
    llm.complete_json("sys", "user")
    second = llm._preferred_key

    assert first == 1
    assert second == 2
