"""
The single LLM entry point for the whole project.

`scorer_engine`, the validation agent and the recommendation agent all call Gemini
through this module, so there is exactly one model name, one client construction, one
retry policy and one JSON-parsing contract. Adding a second call site with its own
`genai.Client(...)` is how the four separate `"gemini-3.6-flash"` defaults drifted apart
in the first place.

Contract, deliberately strict:
  * A failed call RAISES. It never returns a partial or default-filled object.
    Downstream code turns that into a visible failure rather than a plausible score.
  * `generate_json` returns parsed JSON or raises. Callers do their own field
    validation; this module only guarantees "the model answered with valid JSON".
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

import config
import config as config_module

logger = logging.getLogger("resume_intelligence.llm")

try:
    from google import genai
    HAS_NEW_GENAI = True
except ImportError:  # pragma: no cover - legacy fallback
    import google.generativeai as legacy_genai
    HAS_NEW_GENAI = False


class LLMError(RuntimeError):
    """The model could not be reached, or did not return usable JSON."""

    def __init__(self, message: str, *, stage: str):
        super().__init__(message)
        self.stage = stage


MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 1.5

# Status codes that mean "this model cannot serve you right now" rather than "your
# request is wrong". Retrying the same model against these mostly burns the clock —
# a 504 costs ~40s per attempt — so they move the call to the next model instead.
#   503 UNAVAILABLE        the model is experiencing high demand
#   504 DEADLINE_EXCEEDED  it accepted the request and then ran out of time
#   429 RESOURCE_EXHAUSTED quota, which on the free tier is counted per model
_OVERLOADED = ("503", "504", "429", "499", "UNAVAILABLE", "DEADLINE_EXCEEDED",
               "RESOURCE_EXHAUSTED", "CANCELLED", "Timeout", "timed out")

# A different model cannot fix a bad key or a malformed request, so these stop
# everything immediately rather than working through the chain three times over.
_PERMANENT = ("400", "401", "403", "PERMISSION_DENIED", "UNAUTHENTICATED", "INVALID_ARGUMENT")


def _classify(exc: Exception) -> str:
    """`overloaded`, `permanent`, or `transient` — from the SDK's message text."""
    text = f"{type(exc).__name__}: {exc}"
    if any(token in text for token in _PERMANENT):
        return "permanent"
    if any(token in text for token in _OVERLOADED):
        return "overloaded"
    return "transient"


def model_name() -> str:
    """The primary model. What the system reports it is configured to use."""
    return config.GEMINI_MODEL_NAME


def model_chain() -> list:
    """Primary first, then each fallback, with duplicates dropped."""
    chain = [config.GEMINI_MODEL_NAME] + list(config.GEMINI_FALLBACK_MODELS)
    return list(dict.fromkeys(m for m in chain if m))


# A model that answered 429 is out of quota, which on the free tier resets daily rather
# than in seconds. Re-probing it on each of the six calls in an evaluation just burns
# time, so it is parked briefly. Kept in-process and short: this is an optimisation, not
# a record of entitlement, and a wrong guess costs one extra attempt after it expires.
_QUOTA_COOLDOWN_SECONDS = 600.0
# Parked by (key, model), because quota is counted per model per project. The same model
# on a different project's key is a fresh allowance, so only that one pair is out.
_cooled_off: Dict[tuple, float] = {}


def _park(key: str, model: str) -> None:
    _cooled_off[(key, model)] = time.monotonic() + _QUOTA_COOLDOWN_SECONDS


def _is_parked(key: str, model: str) -> bool:
    until = _cooled_off.get((key, model))
    if until is None:
        return False
    if time.monotonic() >= until:
        del _cooled_off[(key, model)]
        return False
    return True


def _is_quota(exc: Exception) -> bool:
    text = f"{exc}"
    return "429" in text or "RESOURCE_EXHAUSTED" in text


_last_model_used: Optional[str] = None


def last_model_used() -> Optional[str]:
    """Which model actually answered, which is not always the configured one."""
    return _last_model_used


def _resolve_keys(api_key: Optional[str]) -> list:
    """
    Every key to try, in order.

    An explicit `api_key` argument wins outright — a caller that names one means it. The
    configured list is used otherwise, first entry first.
    """
    keys = [api_key] if api_key else list(config.GEMINI_API_KEYS)
    keys = [k for k in keys if k]
    if not keys:
        raise LLMError(
            "No Gemini API key is configured. Set GEMINI_API_KEY in the server environment.",
            stage="config",
        )
    return keys


def key_count() -> int:
    """How many keys are configured. Never returns the keys themselves."""
    return len(config.GEMINI_API_KEYS)


def _fingerprint(key: str) -> str:
    """A short, non-reversible tag so logs can name a key without printing one."""
    return f"key#{(abs(hash(key)) % 900) + 100}"


class _NextModel(Exception):
    """Internal signal: abandon the remaining keys and move on to the next model."""


def _execute(stage: str, invoke, api_key: Optional[str] = None):
    """
    Run `invoke(model, key)` across the model chain and the key list until one answers.

    The two failure modes need opposite remedies, which is the whole point of this
    function:

      * **Quota (429)** is counted per model per *project*. The model is fine; this key's
        allowance for it is spent. So the same model is retried on the next key, and only
        that (key, model) pair is parked. Keeping the model matters — switching models
        changes who is judging the resume, and scores move with it.
      * **Overload (503/504) or a stall** is the model shedding load. Every key would meet
        the same busy model, so trying more of them only burns the deadline. Move to the
        next model instead, with the full key list available again.

    A permanent error — a rejected key, a malformed request — stops everything at once.
    """
    chain = model_chain()
    keys = _resolve_keys(api_key)
    last_error: Optional[Exception] = None
    attempted = False

    # Parking is an optimisation, never the reason a run has nothing left to try. If
    # every pair is currently parked, the passes below ignore parking entirely.
    for honour_parking in (True, False):
        for model in chain:
            try:
                for key in keys:
                    if honour_parking and _is_parked(key, model):
                        continue
                    attempted = True
                    for attempt in range(1, MAX_ATTEMPTS + 1):
                        try:
                            return invoke(model, key), model
                        except Exception as exc:  # noqa: BLE001
                            last_error = exc
                            kind = _classify(exc)
                            if kind == "permanent":
                                raise LLMError(f"{stage} failed against {model}: {exc}",
                                               stage=stage) from exc
                            if kind == "overloaded":
                                if _is_quota(exc):
                                    _park(key, model)
                                    logger.warning(
                                        "%s: %s is out of quota on %s; trying the next key",
                                        stage, model, _fingerprint(key))
                                    break                      # next key, same model
                                logger.warning(
                                    "%s: %s is unavailable (%s); trying the next model",
                                    stage, model, str(exc)[:100])
                                raise _NextModel               # skip the remaining keys
                            if attempt < MAX_ATTEMPTS:
                                logger.warning("%s: attempt %d/%d on %s failed (%s); retrying",
                                               stage, attempt, MAX_ATTEMPTS, model, exc)
                                time.sleep(BACKOFF_SECONDS * attempt)
            except _NextModel:
                continue
        if attempted:
            break          # a real attempt was made; do not repeat ignoring parking

    # Models are named because that is what a reader needs to debug; keys are counted
    # only, since the message reaches logs and error responses.
    raise LLMError(
        f"{stage} failed against every model tried ({', '.join(chain)}) "
        f"on {len(keys)} key(s): {last_error}",
        stage=stage,
    )


def generate_text(
    *,
    prompt: str,
    config: Dict[str, Any],
    api_key: Optional[str] = None,
    stage: str = "llm",
) -> str:
    """
    Raw response text, with the same model chain and deadline as `generate_json`.

    For callers that own their own request config and their own parsing — the scoring
    engine and the resume parser both send a `response_schema` and validate the result
    themselves, and their prompts are matched to the signal corpora, so nothing about
    the request is reinterpreted here. Only the transport is shared: which model is
    tried, how long it gets, and what counts as worth retrying.

    The caller's `config` is passed through untouched apart from an injected deadline.
    """
    global _last_model_used

    request = dict(config)
    request.setdefault(
        "http_options", {"timeout": int(config_module.GEMINI_TIMEOUT_SECONDS * 1000)}
    )

    def invoke(model, key):
        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model=model, contents=prompt, config=request
        )
        text = response.text
        if not text or not text.strip():
            raise ValueError("the model returned an empty body")
        return text

    text, model_used = _execute(stage, invoke, api_key)
    _last_model_used = model_used
    return text


def generate_json(
    *,
    prompt: str,
    system_instruction: str,
    api_key: Optional[str] = None,
    stage: str = "llm",
    temperature: float = 0.2,
) -> Dict[str, Any]:
    """
    One JSON-mode call.

    Retries transient failures against the same model, and moves to the next model in
    the chain when the current one is shedding load — Gemini's "high demand" 503 is
    per-model, so a sibling usually answers immediately where a retry would not. Raises
    only once every model has been tried.
    """
    global _last_model_used

    def invoke(model, key):
        if HAS_NEW_GENAI:
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "system_instruction": system_instruction,
                    "response_mime_type": "application/json",
                    "temperature": temperature,
                    # Milliseconds. Without this an overloaded model can stall for
                    # minutes instead of failing, and the chain never fires.
                    "http_options": {
                        "timeout": int(config_module.GEMINI_TIMEOUT_SECONDS * 1000)
                    },
                },
            )
            text = response.text
        else:  # pragma: no cover - legacy path
            legacy_genai.configure(api_key=key)
            client = legacy_genai.GenerativeModel(
                model_name=model,
                system_instruction=system_instruction,
                generation_config={
                    "response_mime_type": "application/json",
                    "temperature": temperature,
                },
            )
            text = client.generate_content(prompt).text

        if not text or not text.strip():
            raise ValueError("the model returned an empty body")
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError(f"expected a JSON object, received {type(parsed).__name__}")
        return parsed

    parsed, model_used = _execute(stage, invoke, api_key)
    _last_model_used = model_used
    return parsed


def available() -> bool:
    return bool(config.GEMINI_API_KEY)
