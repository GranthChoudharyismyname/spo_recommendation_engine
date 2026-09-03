"""
Extraction and hard-signal tests.

Covers the two things the integration brief calls out as untested: the optional-import
fallback branches actually working, and branch detection not being decided by incidental
prose. Runs offline — no model calls.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND / "app"), str(BACKEND / "scoring")]

import pytest  # noqa: E402

import resume_parser as rp  # noqa: E402
from scorer_engine import extract_deterministic_signals  # noqa: E402

SAMPLE = BACKEND.parent / "frontend" / "public" / "sample-resume.pdf"


def signals(department: str, raw_text: str, track: str = "SDE"):
    resume = {
        "Department": department,
        "Academic Qualifications": [],
        "Work Experience": [],
        "Position of Responsibility": [],
    }
    return extract_deterministic_signals(resume, raw_text, track)[0]


# ---------------------------------------------------------------- content parsing

def test_block_extraction_produces_usable_text():
    text = rp.extract_pdf_markdown(str(SAMPLE))
    assert len(text) > 500
    # The block sorter exists to preserve word spaces in LaTeX-justified text; a flat
    # text dump runs them together.
    assert "Indian Institute of Technology Kanpur" in text


def test_branch_detection_does_not_depend_on_the_text_reader():
    """
    Branch is read from the Department field first and the raw text only as a fallback,
    so it must survive whichever reader produced that text — that was the defect this
    suite exists to prevent.
    """
    text = rp.extract_pdf_markdown(str(SAMPLE))
    for track in ("SDE", "CORE_TECHNOM", "QUANT", "ANALYST_AIML", "CONSULT_PM"):
        assert signals("Computer Science and Engineering", text, track)["branch"] == "CSE", track


# ---------------------------------------------------------------- branch detection

# The exact line from a real resume that used to break this.
OLYMPIAD_LINE = (
    "Archisman Dhar Junior Undergraduate Department of Electrical Engineering. "
    "Secured top 1% class VIII-XII in Indian Olympiad Qualifier in Mathematics (IOQM) 2020"
)


def test_department_field_beats_incidental_prose():
    """
    'Olympiad Qualifier in Mathematics' must not classify an EE candidate as MTH.
    On CORE_TECHNOM that misread is a 15-point pillar swing (EE 20 vs MTH 5).
    """
    for track in ("SDE", "CORE_TECHNOM", "QUANT", "ANALYST_AIML"):
        s = signals("Electrical Engineering", OLYMPIAD_LINE, track)
        assert s["branch"] == "EE", f"{track} misdetected as {s['branch']}"
        assert s["branch_source"] == "department_field"


def test_core_technom_branch_score_is_correct_for_ee():
    resume = {
        "Department": "Electrical Engineering", "Academic Qualifications": [],
        "Work Experience": [], "Position of Responsibility": [],
    }
    _, det = extract_deterministic_signals(resume, OLYMPIAD_LINE, "CORE_TECHNOM")
    assert det["Branch"] == 20, "EE is the top branch on CORE_TECHNOM"


def test_raw_text_fallback_still_runs_when_the_field_is_empty():
    s = signals("", "Department of Mechanical Engineering, IIT Kanpur", "CORE_TECHNOM")
    assert s["branch"] == "ME"
    assert s["branch_source"] == "raw_text_fallback"


def test_priority_order_still_resolves_a_dual_degree():
    """Two departments in one field is genuine ambiguity; track priority decides it."""
    dual = "Computer Science and Engineering | Electrical Engineering"
    assert signals(dual, "", "SDE")["branch"] == "CSE"          # CSE ranks first for SDE
    assert signals(dual, "", "CORE_TECHNOM")["branch"] == "EE"  # EE ranks first for CORE


def test_unrecognised_department_reports_undetected():
    s = signals("Department of Underwater Basket Weaving", "nothing relevant here", "SDE")
    assert s["branch"] == "OTHER"
    assert s["branch_source"] == "undetected"


# ---------------------------------------------------------------- signal compatibility

def test_detected_analyst_firms_keeps_its_original_semantics():
    """
    The extracted signal corpora were produced against this exact behaviour: a regex match
    over a fixed 12-firm list, returning the literal list entries. The knowledge graph is
    published under separate keys so these values stay comparable.
    """
    resume = {
        "Department": "Computer Science and Engineering", "Academic Qualifications": [],
        "Work Experience": [
            {"organization": "Goldman Sachs", "role": "Analyst Intern"},
            {"organization": "Adobe, India", "role": "Research Intern"},
            {"organization": "Tessellate Systems", "role": "Backend Intern"},
        ],
        "Position of Responsibility": [],
    }
    s, _ = extract_deterministic_signals(resume, "", "SDE")

    # Goldman Sachs is on the original list; Adobe is not, however well the KG knows it.
    assert s["detected_analyst_firms"] == ["Goldman Sachs"]

    # KG resolution is additive and lives elsewhere.
    assert [p["resolved_as"] for p in s["kg_pedigree_firms"]] == ["Goldman Sachs", "Adobe"]
    assert s["kg_unverified_firms"] == ["Tessellate Systems"]


def test_kg_absence_does_not_break_the_scorer():
    """The adapter is optional at import time; without it nothing raises."""
    import scorer_engine as se
    original = se._kg_pedigree
    se._kg_pedigree = lambda name, track: None
    try:
        resume = {
            "Department": "Electrical Engineering", "Academic Qualifications": [],
            "Work Experience": [{"organization": "Goldman Sachs", "role": "Intern"}],
            "Position of Responsibility": [],
        }
        s, _ = extract_deterministic_signals(resume, "", "SDE")
        assert s["detected_analyst_firms"] == ["Goldman Sachs"]   # unaffected
        assert s["kg_pedigree_firms"] == []
        assert s["kg_unverified_firms"] == ["Goldman Sachs"]
    finally:
        se._kg_pedigree = original


# ---------------------------------------------------------------- parser roles

def test_content_and_structure_use_different_parsers_by_design():
    """
    Content parsing produces text for the extractor; structural scoring needs glyph
    positions and font metrics, which a text parse does not carry. The two read the
    document for different purposes and must not be collapsed into one pass.
    """
    import resume_structure
    source = Path(resume_structure.__file__).read_text()
    assert "import fitz" in source
    # Structure works from spans and geometry, never from the flattened content text.
    assert "get_text(\"dict\")" in source or 'get_text("dict")' in source


def test_score_resume_returns_the_content_parse_it_used():
    """
    Grounding must be audited against the text the extractor actually read. Auditing it
    against a separately-produced text dump makes content that only one of them recovers
    — table cells, wrapped rows — look fabricated.
    """
    import inspect
    import scorer_engine as se
    src = inspect.getsource(se.score_resume)
    assert '"raw_markdown": raw_markdown' in src, (
        "score_resume must return the content parse so validation can audit against it"
    )


def test_pipeline_prefers_the_returned_content_parse():
    import inspect
    import pipeline
    src = inspect.getsource(pipeline.evaluate)
    # Both the validation agent and compliance must read the same source.
    assert src.count('result.get("raw_markdown")') >= 2
