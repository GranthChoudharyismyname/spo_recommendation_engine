"""
Evidence coverage: every finding should point somewhere real.

Three kinds of finding need three ways of locating them, and none of them may be a
guess. A textual finding quotes a bullet, which is searched for. A layout finding is
geometric, so it carries the region measured from the spans that produced the score. A
finding that is about a section as a whole falls back to that section's heading, found
from the document's own typography rather than an assumed template.

The one thing that must never happen is a highlight over something the finding is not
about, so an unlocatable finding has to stay unlocated.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND / "app"), str(BACKEND / "scoring")]

import pytest  # noqa: E402

import fitz  # noqa: E402
from evidence import PdfEvidenceLocator  # noqa: E402
from resume_structure import RelaxedResumeParser  # noqa: E402


@pytest.fixture(scope="module")
def resume(tmp_path_factory):
    """A resume with real headings, a tight bottom margin and two font sizes."""
    path = tmp_path_factory.mktemp("ev") / "r.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((40, 40), "Ada Lovelace", fontsize=20)
    page.insert_text((40, 80), "Academic Qualifications", fontsize=13)
    page.insert_text((40, 100), "B.Tech Electrical Engineering, IIT Kanpur", fontsize=10)
    page.insert_text((40, 130), "Key Projects", fontsize=13)
    page.insert_text((40, 150), "Built a pipeline that cut latency by 40 percent", fontsize=10)
    page.insert_text((40, 170), "a tiny footnote line", fontsize=6)
    page.insert_text((40, 830), "last line very near the bottom edge", fontsize=10)
    doc.save(path)
    doc.close()
    return str(path)


# ----------------------------------------------------------- geometric findings


def test_every_failing_layout_metric_has_a_region(resume):
    regions = RelaxedResumeParser(resume).evidence_regions()
    for key in ("margins", "font_size", "word_count", "name_ratio"):
        assert regions.get(key), f"{key} has nowhere to point"


def test_regions_are_normalised_to_the_page(resume):
    """The overlay is drawn on a scaled canvas, so anything outside 0..1 lands wrong."""
    for refs in RelaxedResumeParser(resume).evidence_regions().values():
        for r in refs:
            assert 0.0 <= r["x"] <= 1.0 and 0.0 <= r["y"] <= 1.0
            assert 0.0 < r["width"] <= 1.0 and 0.0 < r["height"] <= 1.0
            assert r["page"] >= 1


def test_the_margin_region_is_the_line_nearest_the_edge(resume):
    """Pointing at the wrong line would be worse than not pointing at all."""
    region = RelaxedResumeParser(resume).evidence_regions()["margins"][0]
    assert region["y"] > 0.9  # the 830pt line, not the header


def test_the_font_size_region_is_the_smallest_text(resume):
    region = RelaxedResumeParser(resume).evidence_regions()["font_size"][0]
    assert "6" in region["text"]


def test_the_name_region_is_the_name(resume):
    assert "Ada" in RelaxedResumeParser(resume).evidence_regions()["name_ratio"][0]["text"]


# ------------------------------------------------------------- section findings


def test_headings_are_discovered_from_typography(resume):
    """Not from a list of expected names — the candidate chose the template."""
    found = {h["text"] for h in PdfEvidenceLocator(resume).headings()}
    assert "Academic Qualifications" in found
    assert "Key Projects" in found


def test_a_section_name_matches_the_heading_the_resume_prints(resume):
    """"Projects" has to find "Key Projects"; the two vocabularies rarely agree."""
    refs = PdfEvidenceLocator(resume).locate_section("Projects")
    assert refs and refs[0].text == "Key Projects"
    assert refs[0].match == "section"


def test_a_missing_section_locates_nothing(resume):
    """This resume has no work experience, so a highlight would be a lie."""
    assert PdfEvidenceLocator(resume).locate_section("Work Experience") == []


def test_an_unrelated_section_name_is_not_forced_to_match(resume):
    assert PdfEvidenceLocator(resume).locate_section("Zoology Fieldwork") == []


# ------------------------------------------------------------- textual findings


def test_a_quoted_bullet_is_found_at_its_own_position(resume):
    refs = PdfEvidenceLocator(resume).locate("Built a pipeline that cut latency by 40 percent")
    assert refs and refs[0].match == "exact"
    assert 0.1 < refs[0].y < 0.3


def test_text_that_is_not_in_the_pdf_locates_nothing(resume):
    assert PdfEvidenceLocator(resume).locate("Led a team of forty at a company never mentioned") == []
