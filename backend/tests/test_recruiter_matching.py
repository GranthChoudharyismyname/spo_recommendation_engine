"""
Recruiter matching tests.

The panel answers "which recruiters are worth targeting". Before this, fit depended on
the composite score alone, so every Tier-1 firm scored identically and the shortlist was
effectively arbitrary. These tests hold the properties that make the ranking mean
something: it responds to the candidate, tier ordering survives, and branch history is
evidence rather than a gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND / "app"), str(BACKEND / "scoring")]

import pytest  # noqa: E402

from company_fit import build_company_fit  # noqa: E402
from kg_adapter import load_kg  # noqa: E402
from scorer_engine import ROLE_WEIGHTS  # noqa: E402

kg = load_kg()
pytestmark = pytest.mark.skipif(kg is None, reason="knowledge graph not available")


def names(matches):
    return [m.display_name for m in matches]


# ---------------------------------------------------------------- the pool

def test_the_pool_is_far_larger_than_the_five_once_shown():
    matches = kg.match_recruiters(track="SDE", overall_score=76.0, branch="CSE")
    assert len(matches) > 30, "the SDE pool should be dozens of firms, not a handful"


def test_ppo_dominant_firms_are_excluded_by_construction():
    """Those firms have effectively no campus channel, so the panel must not list them."""
    matches = kg.match_recruiters(track="QUANT", overall_score=80.0, branch="CSE")
    for m in matches:
        assert m.recruiting_mode != "PPO_DOMINANT"
        assert m.iitk_presence != "ppo_only_expected"


# ---------------------------------------------------------------- differentiation

def test_tier_one_firms_are_no_longer_identical():
    """The whole defect: one number for every Tier-1 firm made the order meaningless."""
    tier1 = [m for m in kg.match_recruiters(track="SDE", overall_score=76.0, branch="CSE")
             if m.tier == 1]
    assert len(tier1) > 5
    assert len({m.fit for m in tier1}) > 3, "Tier-1 fits should vary with observed signal"


def test_the_ranking_responds_to_the_candidate_branch():
    ee = names(kg.match_recruiters(track="SDE", overall_score=76.0, branch="EE", limit=8))
    cse = names(kg.match_recruiters(track="SDE", overall_score=76.0, branch="CSE", limit=8))
    assert ee != cse, "branch history should reorder the shortlist"


def test_a_stronger_profile_scores_higher_everywhere():
    weak = {m.company_id: m.fit for m in kg.match_recruiters(
        track="SDE", overall_score=60.0, branch="CSE")}
    strong = {m.company_id: m.fit for m in kg.match_recruiters(
        track="SDE", overall_score=88.0, branch="CSE")}
    shared = set(weak) & set(strong)
    assert shared
    assert all(strong[c] >= weak[c] for c in shared)


# ---------------------------------------------------------------- ordering

def test_tier_one_outranks_uncurated_firms():
    """
    An uncurated firm must not top the list simply by being easy to clear. Defaulting a
    null tier to Tier-4's bar did exactly that.
    """
    matches = kg.match_recruiters(track="SDE", overall_score=76.0, branch="EE", limit=10)
    assert all(m.tier == 1 for m in matches[:5]), [m.tier for m in matches[:5]]
    uncurated = [m for m in kg.match_recruiters(track="SDE", overall_score=76.0) if not m.tier]
    if uncurated:
        top = kg.match_recruiters(track="SDE", overall_score=76.0, limit=20)
        assert not any(m.tier == 0 for m in top[:10])


def test_an_uncurated_tier_is_labelled_not_guessed():
    matches = kg.match_recruiters(track="SDE", overall_score=76.0)
    for m in matches:
        if not m.tier:
            assert m.tier_label == "Tier not curated"


# ---------------------------------------------------------------- branch as evidence

def test_branch_history_is_phrased_as_history_never_eligibility():
    """
    The knowledge graph's own README: render it as history, never as a criterion.
    """
    matches = kg.match_recruiters(track="SDE", overall_score=76.0, branch="EE", limit=20)
    for m in matches:
        low = m.rationale.lower()
        assert "eligible" not in low and "not eligible" not in low
        assert "cannot apply" not in low and "do not apply" not in low
        if m.branch_affinity and m.branch_affinity >= 0.1:
            assert "hiring last cycle came from" in m.rationale


def test_a_branchless_run_still_ranks():
    """Branch is a nudge, never a requirement."""
    assert len(kg.match_recruiters(track="SDE", overall_score=76.0)) > 30


# ---------------------------------------------------------------- panel

def test_the_panel_shows_more_than_five_and_reports_the_pool():
    fit = build_company_fit(76.0, "SDE", {}, ROLE_WEIGHTS["SDE"], branch="CSE")
    assert fit["available"]
    assert fit["shown"] > 5
    assert fit["campus_recruiter_pool"] > fit["shown"]
    assert fit["kg_is_export"] is True


def test_every_track_produces_a_panel():
    for track in ("SDE", "QUANT", "ANALYST_AIML", "CONSULT_PM", "CORE_TECHNOM"):
        fit = build_company_fit(75.0, track, {}, ROLE_WEIGHTS[track], branch="EE")
        assert fit["available"], f"{track} produced no recruiters"
        assert fit["entries"], track
