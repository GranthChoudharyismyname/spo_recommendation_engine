"""
Role-framework loading tests.

The frameworks are the articles the signal corpora were labelled against. Feeding only
the compact rubric meant the evaluator judged against a different standard from the
corpora, so the contract here is that the framework reaches the prompt, is additive, and
never displaces the rubric.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND / "app"), str(BACKEND / "scoring")]

import pytest  # noqa: E402

import role_frameworks as rf  # noqa: E402
from tracks import TRACK_CODES  # noqa: E402


@pytest.fixture(autouse=True)
def clear_cache():
    rf.load.cache_clear()
    yield
    rf.load.cache_clear()


def test_every_track_has_a_framework():
    assert set(rf.FRAMEWORK_FILES) == set(TRACK_CODES)
    for track, available in rf.availability().items():
        assert available, f"{track} framework missing from {rf.framework_dir()}"


def test_frameworks_are_substantially_richer_than_the_rubric():
    from scorer_engine import ROLE_RUBRICS
    for track in TRACK_CODES:
        assert len(rf.load(track)) > len(ROLE_RUBRICS[track]) * 3


@pytest.mark.parametrize("track,marker", [
    ("SDE", "PILLAR 1: BRANCH / DEPARTMENT ELIGIBILITY"),
    ("CONSULT_PM", "SCOPE FRAMEWORK"),
    ("QUANT", "WHAT DILUTES A QUANT RESUME"),
])
def test_the_framework_carries_the_content_the_rubric_omits(track, marker):
    assert marker in rf.load(track).upper()


def test_prompt_section_subordinates_the_framework_to_the_rubric():
    section = rf.prompt_section("SDE")
    assert "takes precedence" in section
    assert "Do not invent bands that are not in the rubric" in section
    assert "SUPPORTING FRAMEWORK — SDE" in section


def test_an_unknown_track_yields_nothing():
    assert rf.load("NOT_A_TRACK") is None
    assert rf.prompt_section("NOT_A_TRACK") == ""


def test_a_missing_directory_degrades_silently(monkeypatch, tmp_path):
    """The pipeline must run without the knowledge base present."""
    monkeypatch.setenv("ROLE_FRAMEWORKS_DIR", str(tmp_path))
    rf.load.cache_clear()
    assert rf.load("SDE") is None
    assert rf.prompt_section("SDE") == ""
    assert not any(rf.availability().values())


def test_oversized_frameworks_are_truncated(monkeypatch, tmp_path):
    (tmp_path / "sde.txt").write_text("x" * (rf.MAX_CHARS + 5_000))
    monkeypatch.setenv("ROLE_FRAMEWORKS_DIR", str(tmp_path))
    rf.load.cache_clear()
    assert len(rf.load("SDE")) == rf.MAX_CHARS


# ---------------------------------------------------------------- wiring

def test_the_scorer_appends_rather_than_substitutes():
    import inspect
    import scorer_engine as se
    src = inspect.getsource(se.evaluate_semantic_with_safety_net)
    # The rubric still leads the prompt.
    assert "{rubric}" in src
    assert "_role_framework(track)" in src
    assert src.index("{rubric}") < src.index("_role_framework(track)")


def test_the_scorer_survives_a_missing_loader():
    import scorer_engine as se
    assert isinstance(se._role_framework("SDE"), str)
    assert se._role_framework("NOT_A_TRACK") == ""
