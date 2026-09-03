"""
Scholastic achievement tests.

The Scholastic Achievements section carries some of the strongest signals on an IITK
resume. The contract here is that tiers come from the role frameworks — not invented
bands — and that a weak rank is reported as diluting rather than silently ignored.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND / "app"), str(BACKEND / "scoring")]

import pytest  # noqa: E402

from scholastic_signals import (  # noqa: E402
    TIER_DILUTING,
    TIER_GOOD,
    TIER_OUTSTANDING,
    TIER_VERY_GOOD,
    extract_from_line,
    extract_scholastic_signals,
)


def one(line, kind=None):
    hits = extract_from_line(line)
    if kind:
        hits = [h for h in hits if h["kind"] == kind]
    assert hits, f"nothing extracted from {line!r}"
    return hits[0]


# ---------------------------------------------------------------- olympiad stages

@pytest.mark.parametrize("line,stage,tier", [
    ("Silver medal at the International Physics Olympiad (IPhO) 2023", "international", TIER_OUTSTANDING),
    ("Selected for OCSC in Astronomy 2023", "camp", TIER_OUTSTANDING),
    ("Qualified Indian National Chemistry Olympiad (INChO) 2024", "national", TIER_VERY_GOOD),
    ("Cleared IOQM 2023", "qualifier", TIER_GOOD),
    ("Among State Top 1% in NSEP 2023", "qualifier", TIER_GOOD),
])
def test_olympiad_stage_is_tiered_not_binary(line, stage, tier):
    """
    The previous `has_olympiad` boolean scored a screening exam and an international
    medal identically. quant.txt §3 treats them as different universes.
    """
    hit = one(line, "olympiad")
    assert hit["stage"] == stage
    assert hit["tier"] == tier


def test_the_previously_undetected_acronyms_are_now_found():
    """IOQM, NSEP and NSEC were absent from the old regex entirely."""
    for acronym in ("IOQM", "NSEP", "NSEC", "IOQC", "RMO"):
        assert extract_from_line(f"Qualified {acronym} 2023"), acronym


# ---------------------------------------------------------------- entrance ranks

@pytest.mark.parametrize("rank,tier", [
    (120, TIER_OUTSTANDING),   # quant.txt: < 200
    (430, TIER_VERY_GOOD),     # quant.txt: < 500
    (900, TIER_GOOD),          # quant.txt: 500-1000 conditional
    (4200, TIER_DILUTING),     # quant.txt: > 1500, advises omitting
])
def test_jee_advanced_bands_follow_the_quant_framework(rank, tier):
    hit = one(f"All India Rank {rank} in JEE Advanced 2023", "entrance_rank")
    assert hit["exam"] == "JEE Advanced"
    assert hit["tier"] == tier


def test_percentile_bands_follow_the_consulting_framework():
    """consult_pm.txt §2.A: top 0.25 percentile Outstanding, top 0.5 Very Good."""
    outstanding = one("Rank 40 in WBJEE among 1.1 Lakh applicants", "entrance_rank")
    assert outstanding["tier"] == TIER_OUTSTANDING
    assert outstanding["cohort"] == 110_000

    diluting = one("Rank 9000 in WBJEE among 1.1 Lakh applicants", "entrance_rank")
    assert diluting["tier"] == TIER_DILUTING


def test_a_rank_binds_to_the_nearest_exam_not_the_first_listed():
    """
    "642/720 in NEET ... and Rank 40 in WBJEE" — the rank is WBJEE's. Taking the first
    exam in list order attributed it to NEET.
    """
    hit = one(
        "Scored 642/720 in NEET(UG) 2024 and secured Rank 40 in WBJEE 2024 "
        "examination among 1.1 Lakh applicants",
        "entrance_rank",
    )
    assert hit["exam"] == "WBJEE"
    assert hit["rank"] == 40


def test_cohort_magnitudes_are_expanded():
    assert one("Rank 500 among 2 Lakh candidates", "entrance_rank")["cohort"] == 200_000
    assert one("Rank 90 among 12,000 applicants", "entrance_rank")["cohort"] == 12_000


def test_a_rank_without_a_cohort_is_not_over_claimed():
    hit = one("Secured Rank 3400 in a state entrance", "entrance_rank")
    assert hit["tier"] == TIER_GOOD
    assert hit["percentile"] is None
    assert "cohort size" in hit["basis"]


# ---------------------------------------------------------------- awards

@pytest.mark.parametrize("line,tier", [
    ("Academic Excellence Award, IIT Kanpur 2024", TIER_VERY_GOOD),
    ("Awarded the Quadeye Excellence Scholarship", TIER_OUTSTANDING),
    ("Selected for SURGE 2025 research programme", TIER_OUTSTANDING),
    ("Received UG admission offer letter from IISc Bangalore", TIER_VERY_GOOD),
])
def test_awards_and_fellowships(line, tier):
    assert one(line, "award")["tier"] == tier


# ---------------------------------------------------------------- aggregation

RESUME = {"Scholastic Qualifications": [
    "Secured Rank 40 in WBJEE 2024 examination among 1.1 Lakh applicants",
    "Qualified Indian National Chemistry Olympiad (INChO) 2024",
    "Placed among Top 300 in Indian Olympiad Qualifier in Mathematics (IOQM) 2023",
    "Secured AIR 4200 in JEE Advanced 2024",
]}


def test_aggregation_reports_the_strongest_tier():
    out = extract_scholastic_signals(RESUME)
    assert out["strongest_tier"] == TIER_OUTSTANDING
    assert out["olympiad_stage"] == "national"
    assert out["total"] >= 4


def test_diluting_entries_are_surfaced_not_dropped():
    """consult_pm.txt is explicit that a weak rank beside a strong one hurts."""
    out = extract_scholastic_signals(RESUME)
    assert len(out["diluting"]) == 1
    assert out["diluting"][0]["exam"] == "JEE Advanced"
    # ...and a diluting entry never becomes the "strongest".
    assert out["strongest"]["tier"] != TIER_DILUTING


def test_every_signal_carries_its_basis_and_evidence():
    for s in extract_scholastic_signals(RESUME)["signals"]:
        assert s["basis"] and s["evidence"]


def test_scoping_is_the_scholastic_section_first():
    """Matches the engine's discipline of not sweeping the whole document."""
    out = extract_scholastic_signals({"Scholastic Qualifications": []},
                                     raw_text="Silver medal at the International Physics Olympiad")
    assert out["total"] == 1   # fallback used only when the section is empty


def test_scorer_publishes_scholastic_additively():
    from scorer_engine import extract_deterministic_signals
    resume = {**RESUME, "Department": "Electrical Engineering",
              "Academic Qualifications": [], "Work Experience": [],
              "Position of Responsibility": []}
    s, _ = extract_deterministic_signals(resume, "", "SDE")
    assert "scholastic_signals" in s and "scholastic_summary" in s
    # The original booleans are untouched.
    assert "has_olympiad" in s and "has_aea" in s and "jee_adv_air" in s
