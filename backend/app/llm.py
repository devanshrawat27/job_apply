"""Small OpenAI-compatible LLM client with strict JSON output.

Providers
---------
* The user can add their own key in Settings (for example a ChatGPT / OpenAI
  key). Those providers are tried FIRST, so the analyst talks to ChatGPT when
  it is configured.
* The ``LLM_API_KEYS`` env keys (Gemini today) are the fallback.
* All of them speak the same ``/chat/completions`` protocol, so one code path
  handles every provider.

Key handling
------------
* keys are rotated round-robin, so load spreads across all of them; the next
  call starts on the next healthy key
* a key that hits quota / auth / rate limit is put on a cooldown and skipped
  until it expires (429: 90s, 401/403: 1h)
* models that are overloaded (500/502/503/504) or retired (400/404/422) are
  also cooled down, so calls stop wasting time on a model the provider is
  failing
* if every key is cooling down the call fails fast instead of hammering them
* total calls and the time budget are bounded
* keys are never logged
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_ROTATE_KEY_STATUS = {401, 402, 403, 408, 409, 429}
_NEXT_MODEL_STATUS = {400, 404, 422, 500, 502, 503, 504}

_lock = threading.Lock()
_preferred_key = 0

# provider id -> monotonic time until which the key should be skipped
_key_cooldown: dict[str, float] = {}
# "provider id:model" -> monotonic time until which the model should be skipped
_model_cooldown: dict[str, float] = {}

_usage = {"calls": 0, "ok": 0, "next_key": 0, "next_model": 0}

# A scan must never hang for minutes on a rate-limited provider.
TOTAL_BUDGET_S = 120
MAX_CALLS = 8

KEY_COOLDOWN_RATE_LIMIT = 90
KEY_COOLDOWN_AUTH = 3600
MODEL_COOLDOWN_OVERLOAD = 120
MODEL_COOLDOWN_INVALID = 3600


class LLMUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    base_url: str
    api_key: str
    models: tuple[str, ...]
    label: str = ""
    source: str = "env"


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text).strip()


def _keys() -> list[str]:
    return settings.llm_key_list


def _models() -> list[str]:
    return settings.llm_model_list or [settings.llm_model]


def _env_models() -> list[str]:
    return _models()


def _mask(api_key: str) -> str:
    key = (api_key or "").strip()
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


def _spec_id(base_url: str, api_key: str) -> str:
    digest = hashlib.sha256(f"{base_url}|{api_key}".encode("utf-8")).hexdigest()[:16]
    return digest


def _candidates(providers: list[dict[str, Any]] | None = None) -> list[ProviderSpec]:
    """User-configured providers first, then the env fallback keys."""
    specs: list[ProviderSpec] = []
    for item in providers or []:
        key = str(item.get("api_key") or "").strip()
        if not key:
            continue
        models = tuple(str(m).strip() for m in (item.get("models") or []) if str(m).strip())
        if not models:
            models = tuple(_env_models())
        base_url = str(item.get("base_url") or settings.llm_base_url).rstrip("/")
        specs.append(
            ProviderSpec(
                id=f"user:{item.get('id', len(specs))}",
                base_url=base_url,
                api_key=key,
                models=models,
                label=str(item.get("label") or item.get("provider") or "ChatGPT"),
                source="settings",
            )
        )

    for index, key in enumerate(_keys()):
        specs.append(
            ProviderSpec(
                id=index,
                base_url=settings.llm_base_url.rstrip("/"),
                api_key=key,
                models=tuple(_env_models()),
                label="Gemini (env)",
                source="env",
            )
        )
    return specs


def _cooling(store: dict, key) -> bool:
    return store.get(key, 0) > time.monotonic()


def _cool(store: dict, key, seconds: int) -> None:
    with _lock:
        store[key] = time.monotonic() + seconds


def _cool_remaining(store: dict, key) -> int:
    return max(0, int(store.get(key, 0) - time.monotonic()))


def _rotate_next(success_index: int, total: int) -> None:
    """Start the next call on the next key, distributing usage evenly."""
    global _preferred_key
    with _lock:
        _preferred_key = (success_index + 1) % max(1, total)


def _call(url: str, headers: dict, payload: dict) -> tuple[str, Any, int | None]:
    """Return (outcome, value, status) where outcome is ok | next_key | next_model."""
    try:
        with httpx.Client(timeout=settings.llm_timeout_s) as client:
            response = client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("LLM network error on %s: %s", payload.get("model"), type(exc).__name__)
        return "next_model", f"{type(exc).__name__}: {exc}", None

    if response.status_code < 400:
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"] or ""
            return "ok", json.loads(_strip_fences(content)), response.status_code
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            logger.warning("LLM output was not JSON on %s: %s", payload.get("model"), exc)
            return "next_key", f"bad model output: {exc}", response.status_code

    if response.status_code == 400 and "response_format" in payload:
        logger.info("provider rejected response_format, retrying without it")
        payload.pop("response_format", None)
        return _call(url, headers, payload)

    error = f"HTTP {response.status_code} ({payload.get('model')}): {response.text[:180]}"
    logger.warning("LLM call failed: %s", error)

    if response.status_code in _ROTATE_KEY_STATUS:
        return "next_key", error, response.status_code
    if response.status_code in _NEXT_MODEL_STATUS:
        return "next_model", error, response.status_code
    return "next_model", error, response.status_code


def reset_cooldowns() -> None:
    """Used by tests and after changing the key list at runtime."""
    global _preferred_key
    with _lock:
        _key_cooldown.clear()
        _model_cooldown.clear()
        _preferred_key = 0
        for key in _usage:
            _usage[key] = 0


def _spec_state(spec: ProviderSpec) -> dict[str, Any]:
    now = time.monotonic()
    return {
        "id": spec.id,
        "label": spec.label,
        "source": spec.source,
        "masked": _mask(spec.api_key),
        "cooling_for_s": max(0, int(_key_cooldown.get(spec.id, 0) - now)),
    }


def key_state(providers: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Masked key health, for diagnostics. Never includes the key itself."""
    with _lock:
        return [_spec_state(spec) for spec in _candidates(providers)]


def key_state_locked() -> list[dict[str, Any]]:
    now = time.monotonic()
    return [
        {
            "id": spec.id,
            "label": spec.label,
            "source": spec.source,
            "masked": _mask(spec.api_key),
            "cooling_for_s": max(0, int(_key_cooldown.get(spec.id, 0) - now)),
        }
        for spec in _candidates(None)
    ]


def stats() -> dict[str, Any]:
    """Per-process LLM usage counters (single worker, so process == app)."""
    with _lock:
        snapshot = dict(_usage)
        snapshot["keys"] = key_state_locked()
        return snapshot


def _model_key(spec: ProviderSpec, model: str) -> str:
    """Env keys keep the old model-only key so existing cooldown logic and
    tests still work; user providers are namespaced per provider."""
    return model if spec.source == "env" else f"{spec.id}:{model}"


def _ordered_models(spec: ProviderSpec) -> list[str]:
    models = list(spec.models)
    healthy = [
        model for model in models if not _cooling(_model_cooldown, _model_key(spec, model))
    ]
    if healthy:
        return healthy
    return sorted(models, key=lambda model: _model_cooldown.get(_model_key(spec, model), 0))[:1]


def complete_json(
    system: str,
    user: str,
    *,
    max_tokens: int = 1400,
    temperature: float = 0.3,
    retries: int = 0,
    budget_s: float | None = None,
    providers: list[dict[str, Any]] | None = None,
) -> Any:
    """Return parsed JSON from the model, or raise LLMUnavailable.

    ``providers`` is the user's own provider list (ChatGPT/OpenAI, etc.). They
    are tried before the env keys.
    """
    candidates = _candidates(providers)
    if not candidates:
        raise LLMUnavailable("no LLM key configured (add ChatGPT in Settings or set LLM_API_KEYS)")

    deadline = time.time() + (TOTAL_BUDGET_S if budget_s is None else max(0.0, budget_s))
    calls = 0
    last_error = ""

    def out_of_time() -> bool:
        return calls >= MAX_CALLS or time.time() > deadline

    if out_of_time():
        raise LLMUnavailable("LLM time budget exhausted")

    total = len(candidates)
    start = _preferred_key % total

    for offset in range(total):
        if out_of_time():
            break

        spec = candidates[(start + offset) % total]
        if _cooling(_key_cooldown, spec.id):
            continue

        for model in _ordered_models(spec):
            if out_of_time():
                break

            payload: dict[str, Any] = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            }
            url = spec.base_url + "/chat/completions"

            for _ in range(retries + 1):
                if out_of_time():
                    raise LLMUnavailable(last_error or "LLM time budget exhausted")
                calls += 1

                outcome, value, status = _call(
                    url,
                    {
                        "Authorization": f"Bearer {spec.api_key}",
                        "Content-Type": "application/json",
                    },
                    payload,
                )
                with _lock:
                    _usage["calls"] += 1
                    if outcome in _usage:
                        _usage[outcome] += 1
                if outcome == "ok":
                    _rotate_next((start + offset) % total, total)
                    return value

                last_error = str(value)
                if outcome == "next_model":
                    cool = (
                        MODEL_COOLDOWN_OVERLOAD
                        if status in (500, 502, 503, 504)
                        else MODEL_COOLDOWN_INVALID
                    )
                    _cool(_model_cooldown, _model_key(spec, model), cool)
                    break

                # This key is out of quota / rate-limited: park it and move on.
                cool_key = (
                    KEY_COOLDOWN_RATE_LIMIT if status == 429 else KEY_COOLDOWN_AUTH
                )
                _cool(_key_cooldown, spec.id, cool_key)
                continue

            if _cooling(_key_cooldown, spec.id) or _cooling(
                _model_cooldown, _model_key(spec, model)
            ):
                break

    all_cooling = all(_cooling(_key_cooldown, spec.id) for spec in candidates)
    if all_cooling:
        wait = min(_cool_remaining(_key_cooldown, spec.id) for spec in candidates)
        raise LLMUnavailable(
            last_error or f"all API keys are cooling down; next retry in ~{wait}s"
        )
    raise LLMUnavailable(last_error or "all API keys and models failed")
