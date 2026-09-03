"""
Acceptance tests for the validation and recommendation agents.

These cover Section 7 of the integration brief. The LLM-backed checks are exercised with
`use_llm=False`, so the suite runs offline and deterministically; the deterministic
pre-filter and every hard rule are still fully tested, which is where the guarantees are.

Run:  python -m pytest tests -q     (from backend/)
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND / "app"), str(BACKEND / "scoring")]

import pytest  # noqa: E402

import recommendation_agent as ra  # noqa: E402
import validation_agent as va  # noqa: E402
from scorer_engine import ROLE_WEIGHTS  # noqa: E402
from tracks import TRACK_CODES, get_track  # noqa: E402


RAW = """
Ananya Deshmukh
Computer Science and Engineering, IIT Kanpur
2026 B.Tech, Computer Science and Engineering, Indian Institute of Technology Kanpur CPI 8.42/10.0
2022 Intermediate/+2, CBSE, Pune 94.20%
Software Development Intern, Sprinklr, Gurugram (May'25 - Jul'25)
Rewrote the batch deduplication stage as a streaming operator over Kafka, cutting
end-to-end ingestion latency from 4.1s to 900ms across 12M daily events in production
Coalesce - a log-structured key-value store | Self Project
Benchmarked against LevelDB on a 40M-key workload, reaching 1.8x write throughput
Coordinator, Programming Club, Students' Gymkhana, IIT Kanpur
"""

RESUME = {
    "Name": "Ananya Deshmukh",
    "Department": "Computer Science and Engineering",
    "Academic Qualifications": [
        {"degree": "B.Tech, Computer Science and Engineering",
         "institution": "Indian Institute of Technology Kanpur",
         "year": "2026", "grade": "CPI 8.42/10.0"},
    ],
    "Work Experience": [
        {"organization": "Sprinklr, Gurugram", "role": "Software Development Intern",
         "duration": "May'25 - Jul'25",
         "description": ["Rewrote the batch deduplication stage as a streaming operator over "
                         "Kafka, cutting end-to-end ingestion latency from 4.1s to 900ms "
                         "across 12M daily events in production"]},
    ],
    "Projects": [
        {"title": "Coalesce - a log-structured key-value store", "organization": "Self Project",
         "duration": "Jan'25 - Apr'25",
         "description": ["Benchmarked against LevelDB on a 40M-key workload, reaching 1.8x "
                         "write throughput"]},
    ],
    "Position of Responsibility": [
        {"position": "Coordinator, Programming Club",
         "organization": "Students' Gymkhana, IIT Kanpur",
         "duration": "Apr'24 - Mar'25", "description": []},
    ],
}


def make_result(**overrides):
    result = {
        "overall_score": 83, "verdict": "Outstanding (Strong Shortlist Contender)",
        "content_score": 81, "structural_score": 93,
        "extracted_signals": {"branch": "CSE", "cpi": 8.42, "cpi_status": "VERIFIED",
                              "por_tier": 4, "jee_adv_air": None, "cf_rating": None},
        "deterministic_scores": {"Academics": 16, "Branch": 20, "Leadership": 14},
        "pillars": {
            "Academics & CPI": {"score": 16, "tier": "Very Good"},
            "Branch Match": {"score": 20, "tier": "Very Good"},
            "Work Experience": {"score": 13, "tier": "Good",
                                "reasoning": "The Sprinklr internship shows a measured "
                                             "production latency improvement."},
            "Projects & Systems Depth": {"score": 16, "tier": "Very Good",
                                         "reasoning": "The storage engine benchmarks against "
                                                      "a real baseline."},
            "SCOPE Articulation": {"score": 13, "tier": "Good",
                                   "reasoning": "Strong quantification in two bullets."},
            "Leadership & PoR": {"score": 14, "tier": "Very Good"},
        },
        "semantic_benchmarks": {"semantic_scores": {
            "work_experience_score": 14, "projects_score": 16, "scope_score": 14}},
        "spo_layout_metrics": {}, "structured_resume": copy.deepcopy(RESUME),
    }
    result.update(overrides)
    return result


def run_validation(result, **kw):
    return va.validate(result, track="SDE", raw_markdown=RAW,
                       role_weights=ROLE_WEIGHTS, use_llm=False, **kw)


# ---------------------------------------------------------------- Section 7 criteria

def test_role_weights_sum_to_one_for_every_track():
    """Enforced by a test, not eyeballed."""
    for track, weights in ROLE_WEIGHTS.items():
        assert round(sum(weights.values()), 9) == 1.0, f"{track} sums to {sum(weights.values())}"


def test_track_registry_is_the_single_source_of_truth():
    assert set(TRACK_CODES) == set(ROLE_WEIGHTS.keys())
    for code in TRACK_CODES:
        assert get_track(code).kg_role in {"SDE", "QUANT", "ANALYST", "CONSULT", "CORE"}


def test_clean_result_passes_validation():
    report = run_validation(make_result())
    assert report["status"] in ("PASS", "PASS_WITH_WARNINGS")
    assert not [f for f in report["findings"] if f["severity"] == "BLOCKING"]


def test_a_finding_never_withholds_the_result():
    """
    No status suppresses a score. A resume tool that goes blank when it is least certain
    is backwards: flag it loudly and still show the review.
    """
    result = make_result()
    result["pillars"]["Work Experience"]["score"] = 27   # triggers a CRITICAL finding
    report = run_validation(result)
    assert report["status"] == "NEEDS_REVIEW"
    assert report["status"] != "BLOCKED"
    # The report is a report, not a gate: the score is untouched by it.
    assert result["overall_score"] == 83


def test_ungrounded_reasoning_is_a_warning_not_a_critical_finding():
    """
    It audits the evaluator's WORDING, not the candidate's claims. "The projects show
    C++ depth" when C++ is in the skills list but not named in a project is loose prose,
    not a fabricated fact.
    """
    import re as _re

    def fake(*, prompt, system_instruction, api_key=None, stage="", temperature=0.0):
        if stage == "reasoning-grounding":
            pillars = _re.findall(r'"pillar": "([^"]+)"', prompt)
            return {"verdicts": [{"pillar": p, "verdict": "UNGROUNDED", "note": "broader"}
                                 for p in pillars]}
        return {"verdicts": []}

    import validation_agent as agent
    original = agent.generate_json
    agent.generate_json = fake
    try:
        report = agent.validate(make_result(), track="SDE", raw_markdown=RAW,
                                role_weights=ROLE_WEIGHTS, use_llm=True)
    finally:
        agent.generate_json = original

    reasoning = [f for f in report["findings"] if f["check"] == "UNGROUNDED_REASONING"]
    assert reasoning, "the check should still fire"
    assert all(f["severity"] == "WARNING" for f in reasoning)
    assert report["status"] == "PASS_WITH_WARNINGS"


def test_fabricated_company_is_flagged():
    """A hand-injected organisation absent from the PDF text must be caught."""
    result = make_result()
    result["structured_resume"]["Work Experience"].append({
        "organization": "Citadel Securities", "role": "Quantitative Trading Intern",
        "duration": "Dec'24 - Feb'25",
        "description": ["Built a market-making model on tick data"],
    })
    report = run_validation(result)
    checks = [f["check"] for f in report["findings"]]
    assert "UNGROUNDED_EXTRACTION" in checks, report["findings"]
    assert report["status"] in ("PASS_WITH_WARNINGS", "NEEDS_REVIEW")


FABRICATED_METRIC = "Improved model accuracy to 99.4% on a held-out set of 2.3M records"


def test_fabricated_metric_is_flagged_without_an_auditor():
    """
    Offline the deterministic matcher still catches it, but marks the finding
    unconfirmed — a WARNING, not a BLOCK. Fail closed, not fail silent.
    """
    result = make_result()
    result["structured_resume"]["Projects"][0]["description"].append(FABRICATED_METRIC)
    report = run_validation(result)
    finding = next(f for f in report["findings"] if f["check"] == "UNGROUNDED_EXTRACTION")
    assert finding["severity"] == "WARNING"
    assert finding["evidence"]["confirmed_by_audit"] is False
    assert report["status"] == "PASS_WITH_WARNINGS"


def test_fabricated_metric_blocks_once_the_auditor_confirms_it(monkeypatch):
    """With the auditor reachable, a confirmed fabricated metric BLOCKS the result."""
    def fake_audit(*, prompt, system_instruction, api_key=None, stage="", temperature=0.0):
        # Rule every claim the deterministic matcher escalated as unsupported.
        ids = re.findall(r'"id": "([^"]+)"', prompt)
        return {"verdicts": [{"id": i, "verdict": "UNSUPPORTED",
                              "note": "Not present in the source text."} for i in ids]}

    monkeypatch.setattr(va, "generate_json", fake_audit)
    result = make_result()
    result["structured_resume"]["Projects"][0]["description"].append(FABRICATED_METRIC)
    report = va.validate(result, track="SDE", raw_markdown=RAW,
                         role_weights=ROLE_WEIGHTS, use_llm=True)
    critical = [f for f in report["findings"] if f["severity"] == "CRITICAL"]
    assert critical, report["findings"]
    assert any(f["evidence"].get("confirmed_by_audit") for f in critical)
    assert report["status"] == "NEEDS_REVIEW"


def test_auditor_clearing_a_claim_removes_the_finding(monkeypatch):
    """A paraphrase the matcher could not resolve must not survive as a false positive."""
    def fake_audit(*, prompt, system_instruction, api_key=None, stage="", temperature=0.0):
        ids = re.findall(r'"id": "([^"]+)"', prompt)
        return {"verdicts": [{"id": i, "verdict": "SUPPORTED", "note": "Present, reworded."}
                             for i in ids]}

    monkeypatch.setattr(va, "generate_json", fake_audit)
    result = make_result()
    result["structured_resume"]["Work Experience"].append({
        "organization": "Citadel Securities", "role": "Intern", "duration": "Dec'24",
        "description": [],
    })
    report = va.validate(result, track="SDE", raw_markdown=RAW,
                         role_weights=ROLE_WEIGHTS, use_llm=True)
    assert not any(f["check"] == "UNGROUNDED_EXTRACTION" for f in report["findings"])
    assert report["grounding_coverage"] == 1.0


def test_out_of_range_pillar_is_flagged_as_critical():
    result = make_result()
    result["pillars"]["Work Experience"]["score"] = 27
    report = run_validation(result)
    assert report["status"] == "NEEDS_REVIEW"
    assert any(f["check"] == "PILLAR_BOUNDS" and f["severity"] == "CRITICAL"
               for f in report["findings"])


def test_broken_role_weights_are_flagged_as_critical():
    broken = {**ROLE_WEIGHTS, "SDE": {**ROLE_WEIGHTS["SDE"], "Work Experience": 0.45}}
    report = va.validate(make_result(), track="SDE", raw_markdown=RAW,
                         role_weights=broken, use_llm=False)
    assert report["status"] == "NEEDS_REVIEW"
    assert any(f["check"] == "ROLE_WEIGHTS_SUM" for f in report["findings"])


def test_a_role_outside_the_tier_list_is_distinct_from_having_none():
    """
    Holding an untiered position and holding none are different facts about a candidate,
    and only the second is a gap. The check was renamed from POR_TIER_DETECTION_GAP once
    an untiered role stopped being treated as a detection failure.
    """
    with_entries = make_result()
    with_entries["extracted_signals"]["por_tier"] = 8
    held = run_validation(with_entries)
    assert any(f["check"] == "POR_OUTSIDE_TIER_LIST" for f in held["findings"])

    without = make_result()
    without["extracted_signals"]["por_tier"] = 8
    without["structured_resume"]["Position of Responsibility"] = []
    absent = run_validation(without)
    assert any(f["check"] == "POR_GENUINELY_ABSENT" for f in absent["findings"])
    assert not any(f["check"] == "POR_OUTSIDE_TIER_LIST" for f in absent["findings"])


def test_an_untiered_role_is_not_reported_as_a_candidate_failing():
    """The validation note is read by the recommendation agent; its framing matters."""
    result = make_result()
    result["extracted_signals"]["por_tier"] = 8
    finding = next(f for f in run_validation(result)["findings"]
                   if f["check"] == "POR_OUTSIDE_TIER_LIST")
    assert finding["severity"] != "CRITICAL"
    assert "unrecognis" not in finding["message"].lower()


def test_cpi_fail_closed_detects_a_bypass():
    result = make_result()
    result["extracted_signals"]["cpi_status"] = "UNVERIFIED_MISSING"
    result["extracted_signals"]["cpi"] = None
    result["deterministic_scores"]["Academics"] = 18   # bypassed the baseline of 4
    report = run_validation(result)
    assert any(f["check"] == "CPI_FAIL_CLOSED" for f in report["findings"])
    assert report["status"] == "NEEDS_REVIEW"


def test_branch_department_disagreement_is_flagged_not_resolved():
    result = make_result()
    result["structured_resume"]["Department"] = "Mechanical Engineering"
    report = run_validation(result)
    finding = next((f for f in report["findings"] if f["check"] == "BRANCH_AMBIGUOUS"), None)
    assert finding is not None
    assert finding["severity"] == "WARNING"    # flagged, never silently corrected


@pytest.mark.parametrize("claim,source", [
    ("achieving 13.9x compression", "achieving 13.9\u00d7 compression"),
    ("reduced from 12 -> 1 turns", "reduced from 12 \u2192 1 turns"),
    ("May'25 - Jul'25 at Sprinklr", "May\u201925 \u2013 Jul\u201925 at Sprinklr"),
])
def test_typographic_variants_do_not_read_as_fabrication(claim, source):
    """A PDF writing 13.9× and an extractor writing 13.9x is not a fabricated metric."""
    assert va._fuzzy_contains(claim, source)


@pytest.mark.parametrize("claim,source,why", [
    ("achieving 13.9x compression", "achieving 13.9 \u00d7 compression", "Lexoid puts a space before the unit"),
    ("achieving 13.9x compression", "achieving 13.9\u00d7 compression", "PyMuPDF does not"),
    ("pruned 90% of weights", "pruned 90 % of weights", "space before percent"),
    ("a 268.6K-parameter CNN", "on a 268.6K-parameter CNN", "magnitude suffix attached"),
])
def test_unit_spacing_between_parsers_is_not_fabrication(claim, source, why):
    """
    Content parsing is Lexoid; layout is PyMuPDF. The two space units differently, which
    splits one numeric token in two. That is a parser artefact, not an invented metric.
    """
    assert va._fuzzy_contains(claim, source), why


@pytest.mark.parametrize("claim,source", [
    ("achieving 22.4x compression", "achieving 13.9 \u00d7 compression"),
    ("accuracy of 99.4%", "accuracy of 71.68%"),
    ("a 500K-parameter CNN", "on a 268.6K-parameter CNN"),
])
def test_a_wrong_number_still_fails_despite_the_spacing_tolerance(claim, source):
    """The tolerance must not open a hole: a different figure is still ungrounded."""
    assert not va._fuzzy_contains(claim, source)


def test_a_genuinely_different_number_still_fails():
    assert not va._fuzzy_contains("achieving 22.4x compression", "achieving 13.9\u00d7 compression")


def test_wide_scorer_divergence_is_surfaced():
    result = make_result()
    result["semantic_benchmarks"]["semantic_scores"]["work_experience_score"] = 4
    report = run_validation(result)
    assert any(f["check"] == "SCORER_DIVERGENCE" for f in report["findings"])


# ---------------------------------------------------------------- recommendation agent

def test_attribution_ranks_by_leverage_not_raw_score():
    """
    SCOPE (13/20, 10% weight) has a LOWER score than Projects (16/20, 20% weight) but
    less leverage. Ranking by raw score would put SCOPE first; it must not.
    """
    attribution = ra.attribute_gap(make_result(), "SDE", ROLE_WEIGHTS["SDE"])
    ranked = attribution["ranked_pillars"]
    assert ranked[0]["pillar"] == "Work Experience"       # 13/20 at 25% -> most leverage
    by_name = {p["pillar"]: p["headroom_points"] for p in ranked}
    assert by_name["Projects & Systems Depth"] > by_name["SCOPE Articulation"]
    assert by_name["Academics & CPI"] > 0


def test_attribution_reports_distance_to_next_band():
    result = make_result(overall_score=74)
    attribution = ra.attribute_gap(result, "SDE", ROLE_WEIGHTS["SDE"])
    assert attribution["next_band"]["threshold"] == 80
    assert attribution["next_band"]["points_needed"] == 6.0


def test_exhausted_pillar_has_zero_headroom():
    attribution = ra.attribute_gap(make_result(), "SDE", ROLE_WEIGHTS["SDE"])
    branch = next(p for p in attribution["ranked_pillars"] if p["pillar"] == "Branch Match")
    assert branch["score"] == 20 and branch["headroom_points"] == 0.0


@pytest.mark.parametrize("text", [
    "Just add a 30% improvement metric",
    "Include an impressive metric here",
    "Estimate a number for the impact",
    "Even if you didn't measure it, add something like 20%",
    "Round it up to a cleaner figure",
])
def test_critique_rejects_fabrication(text):
    drafts = [{"id": "r1", "issue": "Weak bullet", "suggested_action": text,
               "evidence_ref": "Rewrote the batch deduplication stage"}]
    kept, rejected = ra.critique(drafts=drafts, validation={"findings": []},
                                 blocked_companies=[], resume=RESUME, api_key=None)
    assert kept == [] and len(rejected) == 1
    assert rejected[0]["rejected_by"] == "code"


@pytest.mark.parametrize("text", [
    "Consider a different track given your branch",
    "You are not eligible for this role",
    "Switch your department to CSE",
])
def test_critique_rejects_eligibility_gating(text):
    drafts = [{"id": "r1", "issue": "Branch", "suggested_action": text,
               "evidence_ref": "Computer Science and Engineering"}]
    kept, rejected = ra.critique(drafts=drafts, validation={"findings": []},
                                 blocked_companies=[], resume=RESUME, api_key=None)
    assert kept == [] and rejected[0]["rejected_by"] == "code"


def test_critique_rejects_ppo_dominant_campus_advice():
    drafts = [{"id": "r1", "issue": "Pedigree",
               "suggested_action": "Apply to Jane Street through the campus cycle.",
               "evidence_ref": "Sprinklr, Gurugram"}]
    kept, rejected = ra.critique(drafts=drafts, validation={"findings": []},
                                 blocked_companies=["Jane Street", "Citadel"],
                                 resume=RESUME, api_key=None)
    assert kept == [] and "intern-to-PPO" in rejected[0]["rejection_reason"]


def test_critique_rejects_items_without_evidence():
    drafts = [{"id": "r1", "issue": "Generic", "evidence_ref": "",
               "suggested_action": "Make your resume stronger."}]
    kept, rejected = ra.critique(drafts=drafts, validation={"findings": []},
                                 blocked_companies=[], resume=RESUME, api_key=None)
    assert kept == [] and "evidence" in rejected[0]["rejection_reason"].lower()


def test_critique_keeps_legitimate_advice():
    drafts = [{
        "id": "r1", "severity": "IMPORTANT", "pillar": "SCOPE Articulation",
        "section": "Projects",
        "issue": "The Coalesce benchmark states throughput but not the read-path result.",
        "evidence_ref": "Benchmarked against LevelDB on a 40M-key workload, reaching 1.8x "
                        "write throughput",
        "suggested_action": "Add the p99 read latency you already recorded in the benchmark run.",
        "expected_impact": "SCOPE Articulation, up to +3.0",
    }]
    kept, rejected = ra.critique(drafts=drafts, validation={"findings": []},
                                 blocked_companies=["Jane Street"], resume=RESUME, api_key=None)
    # The model critique is unreachable offline, so it degrades to keeping the item and
    # marking the pass as not run — the hard-rule gate has already cleared it.
    assert len(kept) == 1 and rejected == []
    assert kept[0]["critique"] == "not_run"


def test_recommendations_are_never_withheld_over_a_finding():
    """
    Advice used to be withheld when validation raised a critical finding. That fired on
    the evaluator's own prose being marginally broader than the resume text, leaving a
    student with a blank page over a wording judgement. Findings are context for the
    advice, not a gate on it.
    """
    attribution = ra.attribute_gap(make_result(), "SDE", ROLE_WEIGHTS["SDE"])
    assert attribution["ranked_pillars"], "attribution must still run"

    # The critique gate still applies; only the refusal is gone.
    kept, rejected = ra.critique(
        drafts=[{"id": "r1", "issue": "Bullet states no outcome",
                 "evidence_ref": "Rewrote the batch deduplication stage",
                 "suggested_action": "State the throughput you measured."}],
        validation={"status": "NEEDS_REVIEW", "findings": [
            {"check": "UNGROUNDED_REASONING", "severity": "WARNING", "message": "x"}]},
        blocked_companies=[], resume=RESUME, api_key=None)
    assert len(kept) == 1 and rejected == []


def test_markdown_summary_is_candidate_safe():
    attribution = ra.attribute_gap(make_result(), "SDE", ROLE_WEIGHTS["SDE"])
    md = ra.to_markdown(
        result=make_result(), track="SDE", attribution=attribution,
        recommendations=[{"severity": "HIGH", "issue": "Work experience is thin on outcomes.",
                          "evidence_ref": "Rewrote the batch deduplication stage",
                          "suggested_action": "State the throughput you measured.",
                          "section": "Work Experience", "pillar": "Work Experience",
                          "expected_impact": "up to +7.4"}],
    )
    assert "candidate_source" not in md
    assert "Where the points are" in md
    assert "did not measure" in md or "did not measure" in md.lower()
