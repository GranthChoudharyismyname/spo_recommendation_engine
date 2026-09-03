"""
SPO guideline configuration tests.

The guidelines are revised each placement cycle, so they are data. These tests hold the
contract that matters: editing the JSON changes behaviour, and a missing or broken file
degrades to the shipped defaults rather than crashing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND / "app"), str(BACKEND / "scoring")]

import pytest  # noqa: E402

import spo_config  # noqa: E402


@pytest.fixture(autouse=True)
def clear_cache():
    spo_config.load.cache_clear()
    yield
    spo_config.load.cache_clear()


def write(tmp_path, payload) -> str:
    p = tmp_path / "spo.json"
    p.write_text(json.dumps(payload))
    return str(p)


# ---------------------------------------------------------------- shipped config

def test_the_shipped_config_loads():
    data = spo_config.load()
    assert data["cycle"] == "2026"
    assert data["layout"]["min_words"] == 500
    assert data["layout"]["max_words"] == 750
    assert len(spo_config.approved_headings()) > 30
    assert "Times New Roman" in spo_config.preferred_fonts()


def test_layout_thresholds_reach_the_structural_scorer():
    from resume_structure import GUIDELINES
    assert GUIDELINES["min_words"] == spo_config.layout()["min_words"]
    assert GUIDELINES["max_font_families"] == spo_config.layout()["max_font_families"]


# ---------------------------------------------------------------- editing a cycle

def test_changing_the_word_count_band_changes_the_config(tmp_path):
    path = write(tmp_path, {"cycle": "2027", "layout": {"min_words": 400, "max_words": 900}})
    assert spo_config.cycle(path) == "2027"
    assert spo_config.layout(path)["min_words"] == 400
    assert spo_config.layout(path)["max_words"] == 900


def test_unspecified_layout_keys_fall_back(tmp_path):
    """A partial config must not drop the keys it did not mention."""
    path = write(tmp_path, {"cycle": "2027", "layout": {"max_words": 900}})
    layout = spo_config.layout(path)
    assert layout["max_words"] == 900
    assert layout["min_content_font_size_pt"] == 9.0   # from the fallback


def test_a_rule_can_be_disabled_without_deleting_it(tmp_path):
    path = write(tmp_path, {"cycle": "2027", "compliance_rules": {
        "SPO_NO_JEE_GATE_RANK": {"enabled": False, "severity": "BLOCKING",
                                 "guideline": "kept for the record"}}})
    assert spo_config.is_enabled("SPO_NO_JEE_GATE_RANK", path) is False
    # Its wording survives, so it can be switched back on next cycle.
    assert spo_config.guideline_text("SPO_NO_JEE_GATE_RANK", "", path) == "kept for the record"


def test_severity_can_be_downgraded_for_a_cycle(tmp_path):
    path = write(tmp_path, {"compliance_rules": {
        "SPO_NO_MOBILE_NUMBER": {"enabled": True, "severity": "WARNING"}}})
    assert spo_config.severity("SPO_NO_MOBILE_NUMBER", "BLOCKING", path) == "WARNING"


def test_an_unknown_rule_defaults_to_enabled(tmp_path):
    path = write(tmp_path, {"compliance_rules": {}})
    assert spo_config.is_enabled("SPO_SOMETHING_NEW", path) is True


# ---------------------------------------------------------------- resilience

def test_a_missing_file_falls_back_without_raising(tmp_path):
    data = spo_config.load(str(tmp_path / "nope.json"))
    assert data["cycle"] == "built-in"
    assert data["layout"]["min_words"] == 500


def test_malformed_json_falls_back_without_raising(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{ not json")
    data = spo_config.load(str(p))
    assert data["cycle"] == "built-in"
    assert data["layout"]["max_font_families"] == 1


# ---------------------------------------------------------------- end to end

def test_disabling_a_rule_removes_its_finding(monkeypatch, tmp_path):
    """The whole point: an SPO change is a config edit, not a code change."""
    import compliance

    resume = {
        "Contact Information": {"email": "a@b.c", "phone": "+91 98765 43210"},
        "Academic Qualifications": [], "Projects": [], "Work Experience": [],
        "Scholastic Qualifications": [],
    }
    raw = "Phone: +91 98765 43210"
    signals = {"cpi_status": "VERIFIED"}

    def run():
        return compliance.evaluate_compliance(
            pdf_path=str(tmp_path / "missing.pdf"), raw_text=raw, resume_json=resume,
            layout_metrics={}, signals=signals, total_pages=1)

    enabled = run()
    assert any(f["check"] == "SPO_NO_MOBILE_NUMBER" for f in enabled["findings"])

    path = write(tmp_path, {"cycle": "2027", "compliance_rules": {
        "SPO_NO_MOBILE_NUMBER": {"enabled": False}}})
    monkeypatch.setenv("SPO_GUIDELINES_PATH", path)
    spo_config.load.cache_clear()

    disabled = run()
    assert not any(f["check"] == "SPO_NO_MOBILE_NUMBER" for f in disabled["findings"])
    assert disabled["cycle"] == "2027"
    assert "SPO_NO_MOBILE_NUMBER" in disabled["rules_disabled"]


def test_the_report_names_the_cycle_it_used():
    import compliance
    out = compliance.evaluate_compliance(
        pdf_path="/nonexistent.pdf", raw_text="", resume_json={},
        layout_metrics={}, signals={}, total_pages=1)
    assert out["cycle"] == "2026"
    assert "SPO_PREFERRED_FONT" in out["rules_disabled"]
