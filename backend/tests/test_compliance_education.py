"""
The education rows of the SPO compliance check.

The rule asks whether the table lists Class XII and Class X with their scores. It used
to answer that by searching the whole table as one lower-cased string for a short list
of spellings, which failed two different ways:

  * Extraction is not deterministic, and the same resume comes back as "CBSE (XII)",
    "Class 12", "ISC", "Higher Secondary" or "AISSCE" on different runs. Seven of nine
    real spellings produced a finding saying the row was missing while it sat in the PDF.
  * "Senior Secondary" contains "secondary", so searching the joined string reported a
    Class X row that did not exist.

And it never looked at the marks at all, though the guideline it quotes asks for scores.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND / "app"), str(BACKEND / "scoring")]

import pytest  # noqa: E402

import compliance as C  # noqa: E402


def row(degree, grade="95%", institution="A School"):
    return {"degree": degree, "institution": institution, "grade": grade, "year": "2022"}


def levels(*degrees):
    return [C._level_of(row(d)) for d in degrees]


# ------------------------------------------------------------- stage detection

@pytest.mark.parametrize("twelfth,tenth", [
    ("CBSE (XII)", "CBSE (X)"),
    ("Class 12", "Class 10"),
    ("ISC", "ICSE"),
    ("Higher Secondary", "Secondary"),
    ("Senior Secondary", "Matriculation"),
    ("XIIth", "Xth"),
    ("AISSCE", "AISSE"),
    ("Grade 12", "Grade 10"),
    ("PUC", "SSLC"),
    ("Intermediate", "10th"),
    ("HSC", "SSC"),
])
def test_both_school_rows_are_recognised(twelfth, tenth):
    """Every one of these is a spelling a real extraction has produced."""
    assert levels(twelfth, tenth) == ["XII", "X"]


def test_senior_secondary_is_not_mistaken_for_a_class_x_row():
    """It contains the word "secondary"; searching the joined table invented a Class X."""
    assert C._level_of(row("Senior Secondary")) == "XII"
    assert C._level_of(row("Higher Secondary")) == "XII"


def test_a_degree_row_is_neither():
    assert C._level_of(row("B.Tech (Electrical Engineering)", "8.2/10")) == "DEGREE"
    assert C._level_of(row("M.Tech Computer Science")) == "DEGREE"
    # An integrated or 10-semester programme must not be read as a Class X row.
    assert C._level_of(row("Integrated M.Sc")) == "DEGREE"
    assert C._level_of(row("Diploma in Engineering")) == "DEGREE"


def test_the_board_may_be_named_in_the_institution_instead():
    assert C._level_of({"degree": "Class XII", "institution": "CBSE"}) == "XII"


def test_a_year_is_not_read_as_a_class():
    assert C._level_of({"degree": "B.Tech 2012-2016", "institution": "IIT Kanpur"}) == "DEGREE"


# ------------------------------------------------------------------ the rule

def run(quals, **signals):
    return C.evaluate_compliance(
        pdf_path="",
        raw_text="",
        resume_json={"Academic Qualifications": quals},
        layout_metrics={},
        signals=signals or {},
        total_pages=1,
    )


def checks(report):
    return {f["check"] for f in report["findings"]}


def test_a_complete_table_raises_nothing_about_education():
    report = run([row("B.Tech (Electrical Engineering)", "8.2/10"),
                  row("CBSE (XII)", "96%"), row("CBSE (X)", "98.2%")])
    assert "SPO_EDUCATION_TABLE_ROWS" not in checks(report)
    assert "SPO_EDUCATION_SCORES" not in checks(report)


def test_an_unusual_spelling_no_longer_reports_a_missing_row():
    """The regression this rewrite exists for."""
    report = run([row("B.Tech", "8.2/10"), row("ISC", "93%"), row("ICSE", "96%")])
    assert "SPO_EDUCATION_TABLE_ROWS" not in checks(report)


def test_a_genuinely_missing_row_is_still_reported():
    report = run([row("B.Tech", "8.2/10"), row("CBSE (XII)", "96%")])
    assert "SPO_EDUCATION_TABLE_ROWS" in checks(report)
    msg = next(f["message"] for f in report["findings"]
               if f["check"] == "SPO_EDUCATION_TABLE_ROWS")
    # Only the absent row is named as missing; the closing sentence restates both.
    named = msg.split("does not appear to list ")[1].split(".")[0]
    assert named == "Class X"


def test_a_row_without_a_score_is_reported():
    """The guideline asks for the scores, not merely the rows."""
    report = run([row("B.Tech", "8.2/10"), row("CBSE (XII)", ""), row("CBSE (X)", "98%")])
    assert "SPO_EDUCATION_SCORES" in checks(report)
    msg = next(f["message"] for f in report["findings"]
               if f["check"] == "SPO_EDUCATION_SCORES")
    assert "Class XII" in msg


def test_scores_in_any_form_count():
    for grade in ("96%", "96", "9.1 CGPA", "8.2/10"):
        report = run([row("CBSE (XII)", grade), row("CBSE (X)", grade)])
        assert "SPO_EDUCATION_SCORES" not in checks(report), grade


# --------------------------------------------------- reading the level generically

@pytest.mark.parametrize("degree,expected", [
    ("Class 12", "XII"), ("XII", "XII"), ("XIIth", "XII"), ("12th", "XII"),
    ("Twelfth Standard", "XII"), ("Grade 12", "XII"), ("+2", "XII"),
    ("Class 10", "X"), ("X", "X"), ("Xth Std", "X"), ("10th", "X"), ("Tenth", "X"),
])
def test_the_level_is_read_from_the_number_itself(degree, expected):
    """Most spellings carry the number, so no board list is needed to place them."""
    assert C._level_of(row(degree)) == expected


# ------------------------------------------------------ abstaining when unsure

@pytest.mark.parametrize("degree", [
    "Cambridge International A Levels", "IGCSE", "Abitur", "Gaokao",
    "Rashtriya Madhyamik Board",
])
def test_an_unfamiliar_qualification_is_unknown_rather_than_guessed(degree):
    assert C._level_of(row(degree)) is None


def test_an_unreadable_row_silences_the_missing_row_finding():
    """
    The balance this rule is built around.

    No vocabulary list covers every board, so the question is what happens at its edge.
    Telling a candidate their Class X is absent while it is printed in the table is a
    worse failure than missing a genuine omission, so a row that cannot be read buys
    silence instead of an accusation.
    """
    report = run([row("B.Tech", "8.2/10"), row("Cambridge A Levels", "A*"), row("IGCSE", "A")])
    assert "SPO_EDUCATION_TABLE_ROWS" not in checks(report)


def test_silence_applies_only_while_something_is_unreadable():
    """Once every row is understood, a real omission is still reported."""
    report = run([row("B.Tech", "8.2/10"), row("CBSE (XII)", "96%")])
    assert "SPO_EDUCATION_TABLE_ROWS" in checks(report)
