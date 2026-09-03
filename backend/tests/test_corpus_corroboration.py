"""
Grounding the qualitative evaluator in the corpus match.

The keyword baseline and the LLM evaluator scored the same pillars from the same resume
without ever seeing each other, so they diverged for reasons neither could explain. The
matched anchors are now shown to the evaluator.

What must not happen is the evaluator being anchored to the baseline's *score*. The
baseline reaches roughly a sixth of each corpus, so a zero usually means it did not know
the vocabulary, not that the projects are weak. Closing the gap by copying a wrong number
would be worse than the gap. These tests hold that line, and the privacy line: corpus
evidence is verbatim text from other candidates' resumes and must never travel.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND / "app"), str(BACKEND / "scoring")]

import pytest  # noqa: E402

import scorer_engine as se  # noqa: E402

MATCHED = {
    "sample_matched_corpus_anchors": ["ml_drowsiness_detection_project", "image_captioning_project"],
    "matched_proj_anchors_count": 5,
    "matched_work_anchors_count": 2,
    "matched_scope_metrics_count": 8,
    "total_role_signals": 234,
    "semantic_scores": {"projects_score": 19, "work_experience_score": 6, "scope_score": 19},
}

NOTHING_MATCHED = {
    "sample_matched_corpus_anchors": [],
    "matched_proj_anchors_count": 0,
    "matched_work_anchors_count": 0,
    "matched_scope_metrics_count": 8,
    "total_role_signals": 113,
    "semantic_scores": {"projects_score": 6, "work_experience_score": 6, "scope_score": 19},
}


def test_matched_anchors_reach_the_evaluator():
    block = se._corpus_corroboration(MATCHED, "SDE")
    assert "ml_drowsiness_detection_project" in block
    assert "project anchors matched: 5" in block


def test_the_baseline_score_is_never_shown():
    """A number in the prompt gets anchored to; the baseline's number is often wrong."""
    for match in (MATCHED, NOTHING_MATCHED):
        block = se._corpus_corroboration(match, "SDE")
        assert "19/20" not in block and "6/20" not in block
        assert "projects_score" not in block
        assert "semantic_scores" not in block


def test_nothing_is_sent_when_the_baseline_found_nothing():
    """
    Measured, not assumed: an earlier version reported "0 anchors matched" with an
    instruction to ignore it, and the evaluator still dropped projects 14 -> 12 and
    SCOPE 10 -> 8 on the same resume. A zero in a prompt gets anchored to. Since the
    baseline reaches about a sixth of each corpus, its zeros are mostly vocabulary
    misses, so the block is omitted entirely.
    """
    assert se._corpus_corroboration(NOTHING_MATCHED, "CORE_TECHNOM") == ""


def test_a_zero_count_is_never_written_into_the_prompt():
    partial = {**MATCHED, "matched_work_anchors_count": 0}
    block = se._corpus_corroboration(partial, "SDE")
    assert "work-experience anchors matched: 0" not in block
    assert "project anchors matched: 5" in block


def test_corpus_evidence_never_travels_into_the_prompt():
    """Anchor evidence is verbatim text from other candidates' resumes."""
    leaky = {
        **MATCHED,
        "sample_matched_corpus_anchors": ["fine_tuned_bert_project"],
        "evidence": "Built a BERT classifier at Acme, cutting review time 40%",
        "candidate_source": "resume_017.pdf",
    }
    block = se._corpus_corroboration(leaky, "SDE")
    assert "Acme" not in block
    assert "resume_017" not in block


def test_it_degrades_to_nothing_when_no_match_is_supplied():
    """The parameter is optional, so an older caller must not break or emit a stub."""
    assert se._corpus_corroboration(None, "SDE") == ""
    assert se._corpus_corroboration({}, "SDE") == ""


def test_the_instruction_forbids_lowering_a_score_to_match_the_baseline():
    src = se.evaluate_semantic_with_safety_net.__doc__ or ""
    import inspect
    body = inspect.getsource(se.evaluate_semantic_with_safety_net)
    assert "raise your confidence but never lower it" in body


def test_the_evaluator_still_accepts_being_called_without_a_corpus_match():
    """Backwards compatible: the production caller was the only one passing it."""
    import inspect
    sig = inspect.signature(se.evaluate_semantic_with_safety_net)
    assert sig.parameters["corpus_match"].default is None
