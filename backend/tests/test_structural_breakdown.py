"""
Structural score breakdown tests.

The breakdown exists to explain a number that used to appear bare, so the contract that
matters is that it cannot drift from the score it claims to explain: the components must
always reconstruct the total, and a resume that loses points must produce findings that
say where they went.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND / "app"), str(BACKEND / "scoring")]

import pytest  # noqa: E402

import recommendations as R  # noqa: E402
import resume_structure as RS  # noqa: E402
from scorer_engine import ROLE_WEIGHTS  # noqa: E402


class FakeParser(RS.RelaxedResumeParser):
    """A parser stubbed at the metric boundary, so no PDF is needed."""

    def __init__(self, metrics, pages=1, words=400):
        self.pages = [None] * pages
        self._metric_cache = None
        self._metrics = metrics
        self._words = words

    def full_text(self):
        return "word " * self._words

    def content_spans(self):
        return [object()]

    def eval_word_count(self):
        return self._metrics["word_count"]

    def eval_margins(self):
        return self._metrics["margins"]

    def eval_font_families(self):
        return self._metrics["font_families"]

    def eval_font_size(self):
        return self._metrics["font_size"]

    def eval_name_ratio(self):
        return self._metrics["name_ratio"]

    def eval_whitespace(self):
        return self._metrics["whitespace"]


def metrics(**overrides):
    base = {
        "word_count": {"ACTUAL_VALUE": 600, "GUIDELINE_VALUE": "500-750", "DELTA": 0},
        "margins": {"ACTUAL_VALUE": "0.6 in", "GUIDELINE_VALUE": "0.5 in", "DELTA": 0.1},
        "font_families": {"ACTUAL_VALUE": 1, "GUIDELINE_VALUE": 1, "DELTA": 0},
        "font_size": {"ACTUAL_VALUE": "9.5 pt", "GUIDELINE_VALUE": "9.0 pt", "DELTA": 0.5},
        "name_ratio": {"ACTUAL_VALUE": 2.2, "GUIDELINE_VALUE": 2.0, "DELTA": 0.2},
        "whitespace": {"ACTUAL_VALUE": "1.20x", "GUIDELINE_VALUE": "1.0-1.45x", "DELTA": 0},
    }
    base.update(overrides)
    return base


def test_components_reconstruct_the_score():
    """The breakdown is the score's own arithmetic, not a second estimate of it."""
    p = FakeParser(metrics(
        margins={"ACTUAL_VALUE": "0.125 in", "GUIDELINE_VALUE": "0.5 in", "DELTA": -0.375},
        font_families={"ACTUAL_VALUE": 10, "GUIDELINE_VALUE": 1, "DELTA": 9},
        font_size={"ACTUAL_VALUE": "5.98 pt", "GUIDELINE_VALUE": "9.0 pt", "DELTA": -3.02},
        word_count={"ACTUAL_VALUE": 817, "GUIDELINE_VALUE": "500-750", "DELTA": 67},
    ))
    breakdown = p.structural_components()
    assert breakdown["total"] == p.calculate_structural_score()
    assert round(sum(c["points_earned"] for c in breakdown["components"])) == breakdown["total"]


def test_a_clean_resume_loses_nothing():
    p = FakeParser(metrics())
    breakdown = p.structural_components()
    assert breakdown["total"] == 100
    assert all(c["points_lost"] == 0 for c in breakdown["components"])


def test_components_are_ordered_by_cost():
    """The expensive problems have to be the ones read first."""
    p = FakeParser(metrics(
        font_families={"ACTUAL_VALUE": 10, "GUIDELINE_VALUE": 1, "DELTA": 9},
        margins={"ACTUAL_VALUE": "0.125 in", "GUIDELINE_VALUE": "0.5 in", "DELTA": -0.375},
    ))
    lost = [c["points_lost"] for c in p.structural_components()["components"]]
    assert lost == sorted(lost, reverse=True)


def test_weights_cover_the_whole_score():
    assert sum(RS.RelaxedResumeParser.COMPONENT_WEIGHTS.values()) == pytest.approx(1.0)
    assert set(RS.RelaxedResumeParser.COMPONENT_WEIGHTS) == set(
        RS.RelaxedResumeParser.COMPONENT_LABELS
    )


def test_blank_document_reports_no_components():
    p = FakeParser(metrics(), words=3)
    breakdown = p.structural_components()
    assert breakdown["blank_document"] is True
    assert breakdown["components"] == []
    assert p.calculate_structural_score() == 0


# ---------------------------------------------------------------- findings


def build(pages=1, **overrides):
    p = FakeParser(metrics(**overrides), pages=pages)
    b = R._Builder(
        result={
            "structural_score": p.calculate_structural_score(),
            "spo_layout_metrics": p._metrics,
            "structural_breakdown": p.structural_components(),
        },
        track="SDE",
        weights=ROLE_WEIGHTS["SDE"],
    )
    R._rule_layout(b)
    return b.items


def rules(items):
    return {i["source_rule"] if isinstance(i, dict) else i.source_rule for i in items}


def test_second_page_is_flagged():
    """A second page is the single largest loss available; it needs its own finding."""
    found = build(pages=2)
    assert "LAYOUT_PAGE_COUNT" in rules(found)


def test_a_clean_resume_raises_no_layout_flags():
    assert build() == []


def test_findings_carry_their_measured_cost():
    """Each finding is worth what its component actually gave up, weighted into the composite."""
    found = build(font_families={"ACTUAL_VALUE": 10, "GUIDELINE_VALUE": 1, "DELTA": 9})
    ff = next(i for i in found if (i["source_rule"] if isinstance(i, dict) else i.source_rule)
              == "LAYOUT_FONT_FAMILIES")
    ff = ff if isinstance(ff, dict) else vars(ff)
    # 20/100 on a 13.6-point component, worth 15% of the composite.
    assert ff["impact_points"] == pytest.approx(1.6, abs=0.1)
    assert "of 13.6 layout points" in ff["rationale"]


def test_a_badly_failing_component_outranks_a_near_miss():
    found = build(
        font_families={"ACTUAL_VALUE": 10, "GUIDELINE_VALUE": 1, "DELTA": 9},
        word_count={"ACTUAL_VALUE": 817, "GUIDELINE_VALUE": "500-750", "DELTA": 67},
    )
    by_rule = {
        (i["source_rule"] if isinstance(i, dict) else i.source_rule):
        (i if isinstance(i, dict) else vars(i))
        for i in found
    }
    assert by_rule["LAYOUT_FONT_FAMILIES"]["severity"] == R.SEVERITY_IMPORTANT
    assert by_rule["LAYOUT_WORD_COUNT"]["severity"] == R.SEVERITY_POLISH


def test_every_layout_finding_lands_in_one_section():
    found = build(pages=2, font_families={"ACTUAL_VALUE": 10, "GUIDELINE_VALUE": 1, "DELTA": 9})
    assert found
    for i in found:
        i = i if isinstance(i, dict) else vars(i)
        assert i["section"] == "Document layout"


# ------------------------------------------------------------- whitespace


def test_padded_line_spacing_is_penalised():
    """Opening the leading to fill a page is the thing this component exists to catch."""
    p = FakeParser(metrics(whitespace={
        "ACTUAL_VALUE": "2.00x", "GUIDELINE_VALUE": "1.0-1.45x", "DELTA": 0.55,
    }))
    ws = next(c for c in p.structural_components()["components"] if c["key"] == "whitespace")
    assert ws["sub_score"] < 40
    assert "LAYOUT_WHITESPACE" in rules(build(whitespace={
        "ACTUAL_VALUE": "2.00x", "GUIDELINE_VALUE": "1.0-1.45x", "DELTA": 0.55,
    }))


def test_single_spacing_is_not_penalised():
    """The band is typographic, so an ordinarily-set resume must score full marks."""
    p = FakeParser(metrics())
    ws = next(c for c in p.structural_components()["components"] if c["key"] == "whitespace")
    assert ws["sub_score"] == 100
    assert "LAYOUT_WHITESPACE" not in rules(build())


def test_cramped_spacing_is_penalised_too():
    p = FakeParser(metrics(whitespace={
        "ACTUAL_VALUE": "0.90x", "GUIDELINE_VALUE": "1.0-1.45x", "DELTA": -0.1,
    }))
    ws = next(c for c in p.structural_components()["components"] if c["key"] == "whitespace")
    assert ws["sub_score"] < 100
