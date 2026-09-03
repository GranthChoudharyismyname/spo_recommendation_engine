"""
Positions of responsibility outside the Gymkhana tier list.

The seven-tier hierarchy covers posts the institute itself confers. A festival vertical,
a hostel body, a chapter of a national society or a role held elsewhere sits outside it
and used to be reported as a title that "did not match", with the advice to rename it.
That is wrong twice over: the role was real, and renaming it would misrepresent it.

These tests hold the replacement contract. The role is read on what it involved — span,
resources, turnout — and the word "unrecognised" never reaches the candidate.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND / "app"), str(BACKEND / "scoring")]

import pytest  # noqa: E402

import por_substance as ps  # noqa: E402
import recommendations as R  # noqa: E402
from scorer_engine import ROLE_WEIGHTS  # noqa: E402


def por(*bullets, position="Events Head", org="Hostel Council"):
    return [{"position": position, "organization": org, "description": list(bullets)}]


def findings(entries):
    b = R._Builder(
        result={
            "structured_resume": {"Position of Responsibility": entries},
            "extracted_signals": {"por_tier": 8},
            "pillars": {"Leadership & PoR": {"score": 3}},
        },
        track="CONSULT_PM",
        weights=ROLE_WEIGHTS["CONSULT_PM"],
    )
    R._rule_por(b)
    return [i if isinstance(i, dict) else vars(i) for i in b.items]


# ----------------------------------------------------------------- extraction


def test_it_reads_team_size():
    out = ps.extract(por("Led 40+ members across 3 verticals to deliver the festival"))
    assert "span" in out["present"]
    assert "40" in ps.summarise("span", out["dimensions"]["span"])


def test_it_reads_budget_and_vendors():
    out = ps.extract(por("Managed a budget of Rs 25L and negotiated with 15+ external vendors"))
    assert "resources" in out["present"]


def test_it_reads_turnout_and_a_safety_record():
    out = ps.extract(por("Handled footfall of 20,000+ with a zero-incident safety record"))
    assert "scale" in out["present"]


def test_a_safety_record_counts_without_any_number():
    """Crisis handling is qualitative; requiring a figure would miss it entirely."""
    assert "scale" in ps.extract(por("Ran the event with an incident-free record"))["present"]


def test_unrelated_numbers_are_not_claimed_as_leadership():
    """Over-claiming would be worse than saying nothing."""
    out = ps.extract(por("Trained a model on 40000 images in 2024 using 3 GPUs"))
    assert out["present"] == []


def test_a_bare_title_evidences_nothing():
    assert ps.extract(por("Organised weekly sessions"))["present"] == []


def test_every_dimension_has_a_label_and_a_prompt():
    for d in ps.DIMENSIONS:
        assert ps.DIMENSION_LABEL[d] and ps.DIMENSION_PROMPT[d]


# ------------------------------------------------------------------- findings


FORBIDDEN = ("unrecognis", "unrecogniz", "did not match", "tier list", "gymkhana designation")


@pytest.mark.parametrize("entries", [
    por("Organised weekly sessions"),
    por("Led 40+ members across 3 verticals"),
    por("Led 40+ members", "Managed Rs 25L budget with 15 vendors", "20,000 footfall, zero-incident"),
])
def test_the_candidate_is_never_told_their_role_is_unrecognised(entries):
    for f in findings(entries):
        blob = f"{f['title']} {f['rationale']} {f['action']}".lower()
        for phrase in FORBIDDEN:
            assert phrase not in blob, f"{phrase!r} reached the candidate"


def test_a_bare_title_is_asked_for_all_three_dimensions():
    f = findings(por("Organised weekly sessions"))[0]
    assert f["detail"]["por_dimensions_missing"] == list(ps.DIMENSIONS)
    for prompt in ps.DIMENSION_PROMPT.values():
        assert prompt in f["action"]


def test_what_is_already_there_is_credited_before_more_is_asked():
    f = findings(por("Led 40+ members across 3 verticals"))[0]
    assert "40" in f["rationale"]
    assert f["detail"]["por_dimensions_present"] == ["span"]
    # and it does not re-ask for the one it just credited
    assert ps.DIMENSION_PROMPT["span"] not in f["action"]


def test_a_fully_evidenced_role_is_not_reported_as_a_shortfall():
    f = findings(por("Led 40+ members", "Rs 25L budget, 15 vendors", "20,000 footfall"))[0]
    assert f["detail"]["por_dimensions_missing"] == []
    assert "fully described" in f["title"]
    assert f["impact_points"] == 0.0


def test_the_action_reads_as_sentences_not_a_run_on():
    """Joining clauses without punctuation produced 'verticals Also state the budget'."""
    action = findings(por("Organised weekly sessions"))[0]["action"]
    assert "Also state" not in action
    assert action.endswith(".")


def test_the_finding_quotes_the_candidates_own_line():
    f = findings(por("Led 40+ members across 3 verticals"))[0]
    assert f["evidence_text"] == "Led 40+ members across 3 verticals"
