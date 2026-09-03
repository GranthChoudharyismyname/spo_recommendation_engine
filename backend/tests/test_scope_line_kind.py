"""
Which bullets SCOPE may ask for a number.

The IITK project tables label rows Objective / Approach / Result, but extraction
flattens them into one list, so every line was assessed identically and objectives were
told to add metrics they cannot have. Two of the five dimensions ask for a figure —
SCALE and EDGE — and only the method and the outcome can carry one.

A recognition ("Received a Pre-Placement Offer", "Awarded Silver") is a matter of
record, not a work claim, and is not assessed at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND / "app"), str(BACKEND / "scoring")]

import pytest  # noqa: E402

import recommendations as R  # noqa: E402
from track_rules import NUMERIC_SCOPE_DIMENSIONS, line_kind, numeric_expected  # noqa: E402
from scorer_engine import ROLE_WEIGHTS  # noqa: E402


@pytest.mark.parametrize("text,kind", [
    ("Received Pre-Placement Offer (PPO) for excellent performance", "RECOGNITION"),
    ("Awarded Silver at Inter IIT Tech Meet 14.0", "RECOGNITION"),
    ("Paper accepted at IEEE IGARSS 2026", "RECOGNITION"),
    ("Built a text-guided interpretation system for Captioning and VQA", "OBJECTIVE"),
    ("Designed a meta-ensemble pipeline using a LLaMA classifier", "APPROACH"),
    ("Fine-tuned Qwen3-VL on VRSBench for captioning", "APPROACH"),
    ("Achieved BLEU4 of 0.79 and Grounding of 0.57", "RESULT"),
    ("Improved transcription accuracy to 86%", "RESULT"),
])
def test_a_bullet_is_classified_by_what_it_is_for(text, kind):
    assert line_kind(text) == kind


def test_only_the_method_and_the_outcome_owe_a_figure():
    assert numeric_expected("APPROACH") and numeric_expected("RESULT")
    assert not numeric_expected("OBJECTIVE")
    assert not numeric_expected("RECOGNITION")


def test_prefix_terms_match_their_inflections():
    """"achiev" with a trailing word boundary cannot match "Achieved" — it did not."""
    for text in ("Achieved 40% lower latency", "Achieving 40% lower latency",
                 "Optimised the query planner using a new index"):
        assert line_kind(text) in ("RESULT", "APPROACH"), text


# ------------------------------------------------------------------- the rule

def findings(bullets):
    resume = {"Projects": [{"title": "A Project", "description": bullets}]}
    b = R._Builder(
        result={"structured_resume": resume,
                "pillars": {"SCOPE Articulation": {"score": 10}}},
        track="SDE", weights=ROLE_WEIGHTS["SDE"],
    )
    R._rule_scope_bullets(b)
    return [i if isinstance(i, dict) else vars(i) for i in b.items]


def test_a_recognition_is_not_assessed_at_all():
    out = findings(["Received Pre-Placement Offer (PPO) for excellent performance"])
    assert out == []


def test_an_objective_is_never_asked_for_a_number():
    out = findings(["Built a text-guided interpretation system for Captioning and VQA"])
    assert len(out) == 1
    asked = out[0]["detail"].get("scope_missing") or []
    for dim in NUMERIC_SCOPE_DIMENSIONS:
        assert dim not in asked, f"{dim} was demanded of an objective line"


def test_an_approach_line_may_still_be_asked_for_a_number():
    out = findings(["Trained a Masked Autoencoder with a ViT backbone via masked modelling"])
    assert len(out) == 1
    asked = out[0]["detail"].get("scope_missing") or []
    assert any(d in asked for d in NUMERIC_SCOPE_DIMENSIONS)


def test_a_fully_satisfied_line_raises_nothing():
    out = findings(["Received Pre-Placement Offer (PPO) for excellent performance"])
    assert out == []


# ------------------------------------------------- which bullet gets picked

def pick(bullets, section="Projects", heading="A Project", key="title"):
    resume = {section: [{key: heading, "description": bullets}]}
    b = R._Builder(
        result={"structured_resume": resume,
                "pillars": {"SCOPE Articulation": {"score": 10}}},
        track="SDE", weights=ROLE_WEIGHTS["SDE"],
    )
    R._rule_scope_bullets(b)
    return [i if isinstance(i, dict) else vars(i) for i in b.items]


def test_an_approach_line_outranks_an_objective_in_the_same_project():
    """
    The regression this exists for.

    Ranking by the raw count of satisfied dimensions favoured objectives, because they
    have only three in play once the two numeric ones are dropped: a 0-of-3 objective
    beat a 1-of-5 method line, so the highlight landed on the objective every time and
    the lines that could actually carry a number were never surfaced.
    """
    out = pick([
        "Built a text-guided interpretation system for Captioning and VQA",   # 0 of 3
        "Trained a Masked Autoencoder with a ViT backbone via masked modelling",  # 1 of 5
    ])
    assert len(out) == 1
    assert out[0]["detail"]["line_kind"] == "APPROACH"


def test_an_objective_is_still_reachable_when_it_is_the_only_line():
    out = pick(["Built a text-guided interpretation system for Captioning and VQA"])
    assert len(out) == 1
    assert out[0]["detail"]["line_kind"] == "OBJECTIVE"


def test_totals_count_only_the_dimensions_that_applied():
    """An objective is scored out of three, not five."""
    out = pick(["Built a text-guided interpretation system for Captioning and VQA"])
    assert out[0]["detail"]["scope_total"] == 3
    for dim in NUMERIC_SCOPE_DIMENSIONS:
        assert dim not in out[0]["detail"]["scope_present"]


def test_competitions_and_research_bullets_are_assessed():
    """
    Only Work Experience and Projects were read, so an Inter-IIT entry — the section
    that actually labels its rows Objective / Approach / Result — was skipped entirely.
    """
    for section, key in (("Major Competitions", "competition"),
                         ("Research Experience", "title")):
        out = pick(["Trained a masked autoencoder with a ViT backbone via masked modelling"],
                   section=section, heading="An Entry", key=key)
        assert len(out) == 1, section
        assert out[0]["section"] == section


# ------------------------------------------- the label the resume actually printed

def test_a_printed_label_overrides_the_sentence_shape():
    """
    Extraction now preserves `description_roles`, so the kind is evidence rather than
    inference. A bullet the candidate filed under Approach is an approach line even
    where its wording reads like an outcome.
    """
    from track_rules import kind_from_label
    assert kind_from_label("Objective") == "OBJECTIVE"
    assert kind_from_label("Result:") == "RESULT"
    assert kind_from_label("Outcome") == "RESULT"
    assert kind_from_label("Impact") == "RESULT"
    assert kind_from_label("") is None          # falls back to inference
    assert kind_from_label(None) is None
    assert kind_from_label("Notes") is None     # unknown label, do not force a kind


def test_a_labelled_objective_is_not_asked_for_a_number():
    """Its wording ("Achieved…") would otherwise read as a result."""
    resume = {"Projects": [{
        "title": "A Project",
        "description": ["Achieved a text-guided interpretation system for captioning"],
        "description_roles": ["Objective"],
    }]}
    b = R._Builder(result={"structured_resume": resume,
                           "pillars": {"SCOPE Articulation": {"score": 10}}},
                   track="SDE", weights=ROLE_WEIGHTS["SDE"])
    R._rule_scope_bullets(b)
    out = [i if isinstance(i, dict) else vars(i) for i in b.items]
    assert out[0]["detail"]["line_kind"] == "OBJECTIVE"
    for dim in NUMERIC_SCOPE_DIMENSIONS:
        assert dim not in out[0]["detail"]["scope_missing"]


def test_missing_or_short_roles_fall_back_to_inference():
    """Older extractions and resumes with no such table must keep working."""
    for roles in ([], ["Objective"], None):
        entry = {"title": "P", "description": [
            "Built a text-guided interpretation system for captioning and VQA",
            "Trained a masked autoencoder with a ViT backbone via masked modelling",
        ]}
        if roles is not None:
            entry["description_roles"] = roles
        b = R._Builder(result={"structured_resume": {"Projects": [entry]},
                               "pillars": {"SCOPE Articulation": {"score": 10}}},
                       track="SDE", weights=ROLE_WEIGHTS["SDE"])
        R._rule_scope_bullets(b)          # must not raise
        assert b.items


def test_the_schema_requires_the_new_field_on_every_work_section():
    from resume_parser import RESUME_SCHEMA
    for sec in ("Work Experience", "Projects", "Research Experience", "Major Competitions"):
        item = RESUME_SCHEMA["properties"][sec]["items"]
        assert "description_roles" in item["properties"], sec
        assert "description_roles" in item["required"], sec


def test_the_description_contract_the_corpora_use_is_unchanged():
    """`description` must stay a plain array of strings; the label rides alongside."""
    from resume_parser import RESUME_SCHEMA
    for sec in ("Work Experience", "Projects", "Research Experience", "Major Competitions"):
        desc = RESUME_SCHEMA["properties"][sec]["items"]["properties"]["description"]
        assert desc == {"type": "array", "items": {"type": "string"}}, sec


# ---------------------------------- resumes that use no Objective/Approach/Result table

@pytest.mark.parametrize("roles", [
    None,                                   # key absent — an older extraction
    [],                                     # present but empty
    ["", "", ""],                           # emitted, no label printed
    ["Objective"],                          # shorter than the bullet list
    ["Objective", "Approach", "Result", "Result"],   # longer than it
    ["Aim", "Method", "Notes"],             # labels this system does not know
    "Objective",                            # malformed: a string, not a list
    {"0": "Objective"},                     # malformed: a mapping
])
def test_every_shape_of_missing_or_broken_labels_falls_back(roles):
    """
    Most resumes do not use the labelled table at all, and a section within one may not
    either. Anything that is not a usable list degrades to reading the sentence, and
    nothing raises.
    """
    entry = {"title": "P", "description": [
        "Built a text-guided interpretation system for captioning and VQA",
        "Trained a masked autoencoder with a ViT backbone via masked modelling",
        "Achieved BLEU4 of 0.79 across the held-out evaluation set",
    ]}
    if roles is not None:
        entry["description_roles"] = roles
    b = R._Builder(result={"structured_resume": {"Projects": [entry]},
                           "pillars": {"SCOPE Articulation": {"score": 10}}},
                   track="SDE", weights=ROLE_WEIGHTS["SDE"])
    R._rule_scope_bullets(b)
    out = [i if isinstance(i, dict) else vars(i) for i in b.items]
    assert out, roles
    assert out[0]["detail"]["line_kind"] in ("OBJECTIVE", "APPROACH", "RESULT")


def test_one_section_may_be_labelled_while_another_is_not():
    """A resume can mix the two conventions; each section is read on its own terms."""
    resume = {
        "Major Competitions": [{
            "competition": "Inter IIT",
            "description": ["Achieved a text-guided interpretation system for captioning"],
            "description_roles": ["Objective"],
        }],
        "Projects": [{
            "title": "Dream Diffusion",
            "description": ["Trained a masked autoencoder with a ViT backbone via masked modelling"],
        }],
    }
    b = R._Builder(result={"structured_resume": resume,
                           "pillars": {"SCOPE Articulation": {"score": 10}}},
                   track="SDE", weights=ROLE_WEIGHTS["SDE"])
    R._rule_scope_bullets(b)
    by_section = {(i if isinstance(i, dict) else vars(i))["section"]:
                  (i if isinstance(i, dict) else vars(i))["detail"]["line_kind"]
                  for i in b.items}
    # The labelled one obeys its label even though the wording says otherwise.
    assert by_section["Major Competitions"] == "OBJECTIVE"
    # The unlabelled one is inferred from the sentence.
    assert by_section["Projects"] == "APPROACH"
