"""
The three named report sections.

Assembled from findings the pipeline already produced, so the contract that matters is
that they cannot disagree with the score beside them: a strength must be a pillar that
actually scored well, and a gap must be a finding that was actually raised. Nothing here
may invent a claim the resume does not support.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND / "app"), str(BACKEND / "scoring")]

import pytest  # noqa: E402

import report_sections as RS  # noqa: E402


def result(**over):
    base = {
        "track": {"short_label": "SDE"},
        "pillars": [
            {"key": "Academics & CPI", "label": "Academics & CPI", "score": 18,
             "max_score": 20, "tier": "Outstanding", "reasoning": "CPI 8.2 with a strong rank.",
             "weight": 0.2},
            {"key": "Work Experience", "label": "Work Experience", "score": 0,
             "max_score": 20, "tier": "Weak", "reasoning": "No work experience.", "weight": 0.25},
        ],
        "extracted_signals": {},
        "structural_breakdown": {"total": 70, "components": []},
        "recommendations": [],
        "compliance": {"findings": []},
    }
    base.update(over)
    return base


# ------------------------------------------------------------------ strengths

def test_a_strong_pillar_becomes_a_strength():
    out = RS.top_strengths(result())
    assert any("Academics" in s["title"] for s in out)


def test_a_weak_pillar_is_never_called_a_strength():
    out = RS.top_strengths(result())
    assert not any("Work Experience" in s["title"] for s in out)


def test_at_most_three_are_returned():
    signals = {
        "scholastic_signals": [{"kind": "entrance_rank", "tier": "outstanding",
                                "evidence": "AIR 1226 in JEE Advanced"}],
        "quantified_results_summary": {"quantified_bullet_ratio": 0.4, "quantified_bullets": 7,
                                       "total_bullets": 18, "total": 19},
        "kg_pedigree_firms": [{"name": "Acme"}],
    }
    out = RS.top_strengths(result(extracted_signals=signals))
    assert len(out) <= RS.MAX_STRENGTHS


def test_each_strength_names_one_distinct_pillar():
    signals = {"scholastic_signals": [{"tier": "outstanding", "evidence": "AIR 1226"}]}
    out = RS.top_strengths(result(extracted_signals=signals))
    assert len({s["pillar"] for s in out}) == len(out)


def test_every_strength_carries_its_evidence():
    """A strength without evidence is encouragement, which is not what this is for."""
    signals = {"quantified_results_summary": {"quantified_bullet_ratio": 0.4,
                                              "quantified_bullets": 7, "total_bullets": 18,
                                              "total": 19}}
    for s in RS.top_strengths(result(extracted_signals=signals)):
        assert s["evidence"].strip()


def test_a_resume_with_nothing_strong_gets_no_invented_strengths():
    weak = result(pillars=[{"key": "Work Experience", "label": "Work Experience", "score": 4,
                            "max_score": 20, "tier": "Weak", "reasoning": "", "weight": 0.25}])
    assert RS.top_strengths(weak) == []


# ----------------------------------------------------------- critical missing

def test_blocking_compliance_outranks_every_point_loss():
    recs = [{"severity": "HIGH", "title": "Big gap", "rationale": "r", "action": "a",
             "section": "Work Experience", "impact_points": 21.0, "source_rule": "X"}]
    compliance = {"findings": [{"severity": "BLOCKING", "check": "SPO_NO_MOBILE_NUMBER",
                                "message": "A mobile number appears on the resume.",
                                "section": "Contact"}]}
    out = RS.critical_missing(recs, compliance)
    assert out[0]["blocking"] is True


def test_only_high_severity_findings_are_called_critical():
    recs = [{"severity": "POLISH", "title": "Minor", "rationale": "r", "action": "a",
             "section": "s", "impact_points": 0.4, "source_rule": "Y"}]
    assert RS.critical_missing(recs, {"findings": []}) == []


def test_gaps_are_ordered_by_what_they_cost():
    recs = [
        {"severity": "HIGH", "title": "Small", "rationale": "", "action": "", "section": "",
         "impact_points": 3.0, "source_rule": "A"},
        {"severity": "HIGH", "title": "Large", "rationale": "", "action": "", "section": "",
         "impact_points": 21.0, "source_rule": "B"},
    ]
    out = RS.critical_missing(recs, {"findings": []})
    assert [i["title"] for i in out] == ["Large", "Small"]


# --------------------------------------------------------- formatting fixes

def test_only_layout_findings_appear_as_formatting_fixes():
    recs = [
        {"severity": "POLISH", "title": "Margins", "rationale": "r", "action": "a",
         "section": "Document layout", "impact_points": 1.7, "source_rule": "LAYOUT_MARGINS_TIGHT",
         "evidence_refs": [{"page": 1, "y": 0.98}]},
        {"severity": "HIGH", "title": "Bullet", "rationale": "r", "action": "a",
         "section": "Projects", "impact_points": 4.0, "source_rule": "SCOPE"},
    ]
    out = RS.formatting_fixes(recs, {"findings": []})
    assert [i["title"] for i in out] == ["Margins"]


def test_a_formatting_fix_keeps_the_region_it_was_measured_from():
    """Line-by-line means each fix can point at the line, not describe it."""
    recs = [{"severity": "POLISH", "title": "Margins", "rationale": "r", "action": "a",
             "section": "Document layout", "impact_points": 1.7,
             "source_rule": "LAYOUT_MARGINS_TIGHT",
             "evidence_refs": [{"page": 1, "y": 0.98, "x": 0.17}]}]
    out = RS.formatting_fixes(recs, {"findings": []})
    assert out[0]["evidence_refs"][0]["y"] == 0.98


def test_pass_fail_layout_rules_join_the_scored_ones():
    compliance = {"findings": [{"severity": "BLOCKING", "check": "SPO_PAGE_COUNT",
                                "message": "The resume runs to three pages.",
                                "guideline": "g", "section": "Document"}]}
    out = RS.formatting_fixes([], compliance)
    assert any(i["source"] == "SPO_PAGE_COUNT" for i in out)


# ------------------------------------------------------------------- assembly

def test_build_returns_all_three_sections():
    out = RS.build(result())
    assert set(out) == {"top_strengths", "critical_missing", "formatting_fixes"}


def test_an_empty_evaluation_produces_empty_sections_not_an_error():
    out = RS.build({})
    assert out == {"top_strengths": [], "critical_missing": [], "formatting_fixes": []}
