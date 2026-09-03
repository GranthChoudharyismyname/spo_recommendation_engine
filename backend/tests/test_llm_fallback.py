"""
Model fallback tests.

Gemini sheds load per-model, so the behaviour that matters is which model a call ends
up on and how much time it wastes getting there. These tests drive each branch with a
stub client: an overloaded model must be abandoned after one attempt rather than
retried, a bad key must not be re-tried against every model in turn, and an ordinary
transient fault must not cause a model switch.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND / "app"), str(BACKEND / "scoring")]

import pytest  # noqa: E402

import llm  # noqa: E402


class FakeClient:
    """Records every model it is asked for and replays a scripted outcome."""

    calls: list = []
    script: dict = {}

    def __init__(self, api_key=None):
        self.models = self

    def generate_content(self, *, model, contents, config):
        FakeClient.calls.append(model)
        outcome = FakeClient.script.get(model, '{"ok": true}')
        if isinstance(outcome, Exception):
            raise outcome
        return types.SimpleNamespace(text=outcome)


@pytest.fixture(autouse=True)
def stub(monkeypatch):
    FakeClient.calls = []
    FakeClient.script = {}
    monkeypatch.setattr(llm, "genai", types.SimpleNamespace(Client=FakeClient))
    monkeypatch.setattr(llm, "HAS_NEW_GENAI", True)
    monkeypatch.setattr(llm.config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm.config, "GEMINI_API_KEYS", ["test-key"])
    monkeypatch.setattr(llm.config, "GEMINI_MODEL_NAME", "gemini-3.6-flash")
    monkeypatch.setattr(llm.config, "GEMINI_FALLBACK_MODELS",
                        ["gemini-3.7-flash", "gemini-3.5-flash"])
    monkeypatch.setattr(llm, "BACKOFF_SECONDS", 0)
    llm._cooled_off.clear()  # parked models are process-global; do not leak across tests


def call():
    return llm.generate_json(prompt="p", system_instruction="s", stage="test")


HIGH_DEMAND = Exception(
    "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently "
    "experiencing high demand.', 'status': 'UNAVAILABLE'}}"
)


def test_high_demand_moves_to_the_next_model():
    """The exact error the user reported has to route to a sibling model."""
    FakeClient.script = {"gemini-3.6-flash": HIGH_DEMAND}
    assert call() == {"ok": True}
    assert FakeClient.calls == ["gemini-3.6-flash", "gemini-3.7-flash"]
    assert llm.last_model_used() == "gemini-3.7-flash"


def test_an_overloaded_model_is_not_retried():
    """Retrying a shedding model burns ~40s per 504 and almost never succeeds."""
    FakeClient.script = {"gemini-3.6-flash": HIGH_DEMAND}
    call()
    assert FakeClient.calls.count("gemini-3.6-flash") == 1


def test_it_walks_the_whole_chain():
    FakeClient.script = {
        "gemini-3.6-flash": HIGH_DEMAND,
        "gemini-3.7-flash": Exception("504 DEADLINE_EXCEEDED"),
    }
    assert call() == {"ok": True}
    assert llm.last_model_used() == "gemini-3.5-flash"


def test_quota_exhaustion_also_falls_back():
    """Free-tier quota is counted per model, so another model is the right remedy."""
    FakeClient.script = {"gemini-3.6-flash": Exception("429 RESOURCE_EXHAUSTED")}
    assert call() == {"ok": True}
    assert llm.last_model_used() == "gemini-3.7-flash"


def test_every_model_down_raises_and_names_them():
    for m in ("gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.5-flash"):
        FakeClient.script[m] = HIGH_DEMAND
    with pytest.raises(llm.LLMError) as err:
        call()
    for m in ("gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.5-flash"):
        assert m in str(err.value)


def test_a_bad_key_fails_immediately():
    """A different model cannot fix an auth problem; trying all three wastes the user's time."""
    FakeClient.script = {"gemini-3.6-flash": Exception("403 PERMISSION_DENIED")}
    with pytest.raises(llm.LLMError):
        call()
    assert FakeClient.calls == ["gemini-3.6-flash"]


def test_a_transient_fault_retries_before_switching():
    """
    Bad JSON is not a load problem, so the same model is retried in full first — only
    once it has failed every attempt does the call move on. This is the opposite of the
    overloaded path, which abandons the model immediately.
    """
    FakeClient.script = {"gemini-3.6-flash": "not json at all"}
    assert call() == {"ok": True}
    assert FakeClient.calls == ["gemini-3.6-flash"] * llm.MAX_ATTEMPTS + ["gemini-3.7-flash"]


def test_a_transient_fault_everywhere_still_raises():
    FakeClient.script = {m: "not json at all"
                         for m in ("gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.5-flash")}
    with pytest.raises(llm.LLMError):
        call()


def test_a_healthy_primary_never_falls_back():
    assert call() == {"ok": True}
    assert FakeClient.calls == ["gemini-3.6-flash"]
    assert llm.last_model_used() == "gemini-3.6-flash"


def test_chain_drops_duplicates(monkeypatch):
    monkeypatch.setattr(llm.config, "GEMINI_FALLBACK_MODELS",
                        ["gemini-3.6-flash", "gemini-3.7-flash"])
    assert llm.model_chain() == ["gemini-3.6-flash", "gemini-3.7-flash"]


def test_fallbacks_can_be_disabled(monkeypatch):
    monkeypatch.setattr(llm.config, "GEMINI_FALLBACK_MODELS", [])
    FakeClient.script = {"gemini-3.6-flash": HIGH_DEMAND}
    with pytest.raises(llm.LLMError):
        call()
    assert FakeClient.calls == ["gemini-3.6-flash"]


def test_a_stalled_model_is_treated_as_overloaded():
    """
    Load-shedding does not always arrive as a 503 — an overloaded model may just stall,
    and the deadline turns that into a cancellation. It must route like a 503, or a slow
    model holds up the whole evaluation instead of being stepped over.
    """
    FakeClient.script = {"gemini-3.6-flash": Exception("499 CANCELLED. The operation was cancelled.")}
    assert call() == {"ok": True}
    assert llm.last_model_used() == "gemini-3.7-flash"
    assert FakeClient.calls.count("gemini-3.6-flash") == 1


def test_a_deadline_is_sent_with_every_request():
    """Without a deadline the fallback chain cannot fire on a stall at all."""
    seen = {}

    class Recorder(FakeClient):
        def generate_content(self, *, model, contents, config):
            seen.update(config)
            return types.SimpleNamespace(text='{"ok": true}')

    import config as cfg
    llm.genai.Client = Recorder
    call()
    assert seen["http_options"]["timeout"] == int(cfg.GEMINI_TIMEOUT_SECONDS * 1000)


def test_a_quota_exhausted_model_is_parked():
    """
    429 is a daily limit, not a momentary spike. Re-probing the same dead model on each
    of the six calls in an evaluation is pure latency, so it is skipped for a while.
    """
    FakeClient.script = {"gemini-3.6-flash": Exception("429 RESOURCE_EXHAUSTED quota")}
    assert call() == {"ok": True}
    FakeClient.calls = []
    assert call() == {"ok": True}
    assert "gemini-3.6-flash" not in FakeClient.calls  # skipped on the second call


def test_parking_expires():
    FakeClient.script = {"gemini-3.6-flash": Exception("429 RESOURCE_EXHAUSTED quota")}
    call()
    llm._cooled_off[("test-key", "gemini-3.6-flash")] = 0.0  # as if it had elapsed
    FakeClient.script = {}
    FakeClient.calls = []
    call()
    assert FakeClient.calls == ["gemini-3.6-flash"]


def test_all_models_parked_still_tries_rather_than_giving_up():
    """Parking is an optimisation; it must never be the reason a run has no models left."""
    for m in llm.model_chain():
        llm._cooled_off[("test-key", m)] = float("inf")
    assert call() == {"ok": True}
