"""
Model fallback on the *scoring* path.

The agent layer routes through `llm.generate_json`, but the scoring engine and the
resume parser own their own prompts and schemas and used to call the SDK directly — so
a "high demand" 503 there failed the whole evaluation while the agents were happily
falling back. These tests pin the scoring path to the same chain, and pin the thing that
must not change with it: the prompt and schema those calls send.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND / "app"), str(BACKEND / "scoring")]

import pytest  # noqa: E402

import llm  # noqa: E402
import resume_parser  # noqa: E402
import scorer_engine  # noqa: E402

HIGH_DEMAND = Exception(
    "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently "
    "experiencing high demand.', 'status': 'UNAVAILABLE'}}"
)

SEMANTIC_REPLY = json.dumps({
    "work_experience_score": 15, "work_experience_tier": "Very Good",
    "work_experience_reasoning": "Solid internships.",
    "projects_score": 15, "projects_tier": "Very Good",
    "projects_reasoning": "Good depth.",
    "scope_articulation_score": 15, "scope_articulation_tier": "Very Good",
    "scope_articulation_reasoning": "Clear outcomes.",
})


class FakeClient:
    calls: list = []
    script: dict = {}
    configs: list = []

    def __init__(self, api_key=None):
        self.models = self

    def generate_content(self, *, model, contents, config):
        FakeClient.calls.append(model)
        FakeClient.configs.append(config)
        outcome = FakeClient.script.get(model)
        if isinstance(outcome, Exception):
            raise outcome
        return types.SimpleNamespace(text=outcome)


@pytest.fixture(autouse=True)
def stub(monkeypatch):
    FakeClient.calls, FakeClient.configs, FakeClient.script = [], [], {}
    monkeypatch.setattr(llm, "genai", types.SimpleNamespace(Client=FakeClient))
    monkeypatch.setattr(llm.config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm.config, "GEMINI_API_KEYS", ["test-key"])
    monkeypatch.setattr(llm.config, "GEMINI_MODEL_NAME", "gemini-3.6-flash")
    monkeypatch.setattr(llm.config, "GEMINI_FALLBACK_MODELS",
                        ["gemini-3.7-flash", "gemini-3.5-flash"])
    monkeypatch.setattr(llm, "BACKOFF_SECONDS", 0)
    llm._cooled_off.clear()  # parked models are process-global; do not leak across tests


def test_scoring_engine_falls_back_on_high_demand():
    """The exact failure the user hit: 503 during evaluation must not end the run."""
    FakeClient.script = {"gemini-3.6-flash": HIGH_DEMAND, "gemini-3.7-flash": SEMANTIC_REPLY}
    out = scorer_engine.evaluate_semantic_with_safety_net(
        resume_json={}, raw_text="x", hard_signals={}, track="SDE", api_key="k",
    )
    assert out["work_experience_score"] == 15
    assert llm.last_model_used() == "gemini-3.7-flash"


def test_scoring_engine_still_sends_its_own_prompt_and_json_mode():
    """Sharing the transport must not reinterpret the request."""
    FakeClient.script = {"gemini-3.6-flash": SEMANTIC_REPLY}
    scorer_engine.evaluate_semantic_with_safety_net(
        resume_json={}, raw_text="x", hard_signals={}, track="SDE", api_key="k",
    )
    cfg = FakeClient.configs[0]
    assert cfg["response_mime_type"] == "application/json"
    assert "system_instruction" in cfg and cfg["system_instruction"]


def test_extraction_falls_back_on_high_demand():
    FakeClient.script = {"gemini-3.6-flash": HIGH_DEMAND,
                         "gemini-3.7-flash": json.dumps({"Name": "A"})}
    assert resume_parser.markdown_to_resume_json("# resume", api_key="k") == {"Name": "A"}
    assert llm.last_model_used() == "gemini-3.7-flash"


def test_extraction_keeps_its_response_schema():
    """
    The schema is the extraction contract the signal corpora were built against. If
    sharing the transport ever drops it, extracted signals change shape silently.
    """
    FakeClient.script = {"gemini-3.6-flash": json.dumps({"Name": "A"})}
    resume_parser.markdown_to_resume_json("# resume", api_key="k")
    cfg = FakeClient.configs[0]
    assert cfg["response_schema"] is resume_parser.RESUME_SCHEMA
    assert cfg["response_mime_type"] == "application/json"


def test_a_deadline_reaches_the_scoring_call_too():
    """Without it, a stalled model hangs the evaluation instead of stepping over."""
    FakeClient.script = {"gemini-3.6-flash": SEMANTIC_REPLY}
    scorer_engine.evaluate_semantic_with_safety_net(
        resume_json={}, raw_text="x", hard_signals={}, track="SDE", api_key="k",
    )
    assert FakeClient.configs[0]["http_options"]["timeout"] > 0


def test_scoring_only_gives_up_after_every_model():
    FakeClient.script = {m: HIGH_DEMAND for m in
                         ("gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.5-flash")}
    with pytest.raises(Exception):
        scorer_engine.evaluate_semantic_with_safety_net(
            resume_json={}, raw_text="x", hard_signals={}, track="SDE", api_key="k",
        )
    assert set(FakeClient.calls) == {"gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.5-flash"}
