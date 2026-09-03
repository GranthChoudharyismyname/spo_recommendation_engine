"""
Evidence-floor tests.

Floors turn two kinds of hard evidence into score guarantees: a knowledge-graph company
tier for work experience, and quantified results for SCOPE. They enforce the bands
ROLE_RUBRICS already states, so the invariants that matter are that they never lower a
score and never exceed the bottom of the band the evidence justifies.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND / "app"), str(BACKEND / "scoring")]

import pytest  # noqa: E402

from evidence_floors import (  # noqa: E402
    PEDIGREE_FLOOR,
    SCHOLASTIC_FLOOR,
    apply_floors,
    pedigree_floor,
    scholastic_floor,
    scope_floor,
)


def firms(*specs):
    return [{"organization": o, "resolved_as": o, "tier": t, "edge_type": e}
            for o, t, e in specs]


def summary(quantified, total, figures=12):
    return {"total": figures, "total_bullets": total, "quantified_bullets": quantified,
            "quantified_bullet_ratio": round(quantified / total, 3),
            "named_metrics": ["accuracy", "latency"]}


# ---------------------------------------------------------------- the core invariant

@pytest.mark.parametrize("we,scope", [(19, 18), (20, 20), (18, 16)])
def test_a_floor_never_lowers_a_score(we, scope):
    signals = {"kg_pedigree_firms": firms(("Adobe", 1, "recruits_for")),
               "quantified_results_summary": summary(9, 10)}
    out_we, out_scope, _, adjustments = apply_floors(
        work_experience_score=we, scope_score=scope, signals=signals)
    assert out_we == we and out_scope == scope
    assert adjustments == []


def test_adjustments_are_only_recorded_when_something_changed():
    signals = {"kg_pedigree_firms": firms(("Adobe", 1, "recruits_for"))}
    *_, none_needed = apply_floors(work_experience_score=19, scope_score=15, signals=signals)
    assert none_needed == []
    *_, applied = apply_floors(work_experience_score=9, scope_score=15, signals=signals)
    assert len(applied) == 1 and applied[0]["from"] == 9 and applied[0]["to"] == 18


# ---------------------------------------------------------------- pedigree

@pytest.mark.parametrize("tier,expected", [(1, 18), (2, 14), (3, 10)])
def test_pedigree_floor_matches_the_rubric_band_bottom(tier, expected):
    f = pedigree_floor({"kg_pedigree_firms": firms(("SomeFirm", tier, "recruits_for"))})
    assert f["floor"] == expected == PEDIGREE_FLOOR[tier]


def test_tier_4_and_unknown_get_no_floor():
    assert pedigree_floor({"kg_pedigree_firms": firms(("Neutral Co", 4, "recruits_for"))}) is None
    assert pedigree_floor({"kg_pedigree_firms": []}) is None
    assert pedigree_floor({}) is None


def test_the_best_tier_wins_across_multiple_internships():
    f = pedigree_floor({"kg_pedigree_firms": firms(
        ("Small Co", 3, "recruits_for"), ("Adobe", 1, "recruits_for"))})
    assert f["floor"] == 18 and f["evidence"]["resolved_as"] == "Adobe"


def test_pedigree_for_is_preferred_over_recruits_for_at_equal_tier():
    """
    The KG's two edges are not interchangeable: pedigree_for means an internship there
    is a positive signal when applying for the role, which is exactly this question.
    """
    f = pedigree_floor({"kg_pedigree_firms": firms(
        ("Recruiter Co", 1, "recruits_for"), ("Pedigree Co", 1, "pedigree_for"))})
    assert f["evidence"]["resolved_as"] == "Pedigree Co"
    assert f["evidence"]["edge_is_fallback"] is False


def test_the_recruits_for_fallback_is_flagged_as_such():
    """pedigree_for covers 10 of 78 companies, so the fallback must stay visible."""
    f = pedigree_floor({"kg_pedigree_firms": firms(("Adobe", 1, "recruits_for"))})
    assert f["evidence"]["edge_is_fallback"] is True
    assert f["evidence"]["edge_type"] == "recruits_for"


# ---------------------------------------------------------------- SCOPE

@pytest.mark.parametrize("quantified,total,expected", [
    (7, 10, 16),    # 70%
    (6, 10, 16),    # 60% — band edge
    (4, 10, 13),    # 40%
    (2, 10, None),  # 20% — no floor
])
def test_scope_floor_bands(quantified, total, expected):
    f = scope_floor({"quantified_results_summary": summary(quantified, total)})
    assert (f["floor"] if f else None) == expected


def test_scope_floor_needs_enough_bullets_to_mean_anything():
    """Two of three bullets is 67%, but three bullets is not evidence of a habit."""
    assert scope_floor({"quantified_results_summary": summary(2, 3)}) is None


def test_scope_floor_sits_below_the_ceiling():
    """SCOPE covers scale, context, ownership and proof — not only numbers."""
    f = scope_floor({"quantified_results_summary": summary(10, 10)})
    assert f["floor"] == 16 < 20


def test_floors_are_absent_without_evidence():
    we, scope, acad, adjustments = apply_floors(
        work_experience_score=8, scope_score=9, signals={})
    assert (we, scope, acad, adjustments) == (8, 9, None, [])


# ---------------------------------------------------------------- wiring

def test_score_resume_records_adjustments():
    import inspect
    import scorer_engine as se
    src = inspect.getsource(se.score_resume)
    assert "_evidence_floors" in src
    assert '"evidence_adjustments": evidence_adjustments' in src
    # Applied before pillar assembly so CORE_TECHNOM's blended SCOPE uses the floored value.
    assert src.index("_evidence_floors") < src.index("project_label_map")


def test_floors_survive_a_missing_module():
    """Optional at import time; the scorer must not break without it."""
    import scorer_engine as se
    assert se._evidence_floors(11, 12, {}) == (11, 12, None, [])


# ---------------------------------------------------------------- scholastic

def scholastic(tier, olympiad=None, example="Silver medal at IPhO 2023"):
    return {
        "scholastic_summary": {"strongest_tier": tier, "olympiad_stage": olympiad,
                               "by_tier": {tier: 1}, "total": 1, "diluting_count": 0},
        "scholastic_signals": [{"tier": tier, "basis": "quant.txt §3 — International "
                                "Olympiad Medalists", "evidence": example}],
    }


@pytest.mark.parametrize("tier,expected", [
    ("outstanding", 17),
    ("very_good", 15),
    ("good", None),           # every IITK candidate cleared JEE; a screening exam is not a floor
    (None, None),
])
def test_scholastic_floor_bands(tier, expected):
    f = scholastic_floor(scholastic(tier) if tier else {})
    assert (f["floor"] if f else None) == expected == (SCHOLASTIC_FLOOR.get(tier) if tier else None)


def test_scholastic_floor_raises_academics():
    _, _, acad, adjustments = apply_floors(
        work_experience_score=15, scope_score=15,
        signals=scholastic("outstanding"), academics_score=11)
    assert acad == 17
    assert any(a["pillar"] == "Academics & CPI" for a in adjustments)


def test_academics_is_untouched_when_not_supplied():
    """The scorer computes Academics deterministically; omitting it opts out entirely."""
    _, _, acad, adjustments = apply_floors(
        work_experience_score=15, scope_score=15, signals=scholastic("outstanding"))
    assert acad is None
    assert not any(a["field"] == "academics" for a in adjustments)


def test_a_diluting_entry_never_lowers_academics():
    signals = {
        "scholastic_summary": {"strongest_tier": None, "olympiad_stage": None,
                               "by_tier": {"negative_diluting": 1}, "total": 1,
                               "diluting_count": 1},
        "scholastic_signals": [{"tier": "negative_diluting", "basis": "weak rank",
                                "evidence": "AIR 4200 in JEE Advanced"}],
    }
    _, _, acad, adjustments = apply_floors(
        work_experience_score=15, scope_score=15, signals=signals, academics_score=8)
    assert acad == 8 and adjustments == []


# ---------------------------------------------------------------- CORE pillar naming

def test_scope_floor_uses_the_blended_pillar_name_on_core():
    """
    CORE_TECHNOM folds SCOPE into "Coursework & SCOPE". A floor recorded against
    "SCOPE Articulation" would never match its pillar, so the badge would never render.
    """
    signals = {"quantified_results_summary": summary(8, 10)}
    assert scope_floor(signals, "SDE")["pillar"] == "SCOPE Articulation"
    assert scope_floor(signals, "CORE_TECHNOM")["pillar"] == "Coursework & SCOPE"
    assert scope_floor(signals)["pillar"] == "SCOPE Articulation"
