"""
Quantified-impact extraction tests.

The numbers a candidate reports are the signal that separates describing work from
showing what it achieved, so the extractor is held to the corpora's `impact` shape:
{"metric", "direction", "value", "unit"}. Runs offline.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND / "app"), str(BACKEND / "scoring")]

import pytest  # noqa: E402

from impact_signals import extract_impact, extract_impact_signals  # noqa: E402


def find(results, value):
    return next((r for r in results if r["value"] == value), None)


# ---------------------------------------------------------------- shape

def test_output_matches_the_corpora_impact_shape():
    r = extract_impact("achieving 13.9x compression")[0]
    assert set(r) >= {"metric", "direction", "value", "unit"}
    assert r == {"metric": "compression", "direction": "achieved", "value": 13.9,
                 "unit": "x", "evidence": "achieving 13.9x compression"}


# ---------------------------------------------------------------- detection

def test_before_and_after_pair_is_captured_with_direction():
    rs = extract_impact("Reduced model size from 1051.5 KB to 75.6 KB")
    assert {r["value"] for r in rs} == {1051.5, 75.6}
    assert all(r["direction"] == "decrease" for r in rs)
    assert all(r["unit"] == "bytes" for r in rs)


def test_nearest_metric_wins_not_the_longest():
    """
    "Reduced model size ... while retaining 71.68% accuracy" — the 71.68 belongs to
    accuracy. Picking the longest term in the window would label it "model size".
    """
    rs = extract_impact(
        "Reduced model size from 1051.5 KB to 75.6 KB while retaining 71.68% accuracy"
    )
    assert find(rs, 71.68)["metric"] == "accuracy"
    assert find(rs, 1051.5)["metric"] == "model size"


def test_labelled_values_name_their_own_metric():
    """`<name> = <number>` works for metrics absent from the vocabulary."""
    rs = extract_impact(
        "Achieved scores: Captioning BLEU4 = 0.79, Grounding = 0.57, "
        "Binary VQA = 0.87 and Numeric VQA = 0.58"
    )
    assert len(rs) == 4
    assert find(rs, 0.87)["metric"] == "binary vqa"
    # A leading conjunction must not become part of the metric name.
    assert find(rs, 0.58)["metric"] == "numeric vqa"


def test_label_stopwords_are_stripped():
    rs = extract_impact("Met all five KPIs: 99.7% accuracy and 3.5 ms latency")
    assert find(rs, 99.7)["metric"] == "accuracy"   # not "all five kpis"


def test_count_nouns_become_the_unit():
    """Matches how the corpora record {"value": 30, "unit": "secretaries"}."""
    rs = extract_impact("Leading a team of 32 secretaries")
    assert find(rs, 32.0)["unit"] == "secretaries"


def test_magnitude_suffixes_are_expanded():
    assert find(extract_impact("a budget of INR 1.4 Lakh"), 140000.0) is not None
    assert find(extract_impact("over 12M daily events"), 12_000_000.0) is not None


def test_hyphenated_unit_survives_when_a_magnitude_is_present():
    """
    "4-bit" is an adjective; "268.6K-parameter" is a scale figure whose unit happens to
    be hyphenated. The magnitude suffix is what separates them.
    """
    r = find(extract_impact("a 268.6K-parameter CNN"), 268600.0)
    assert r is not None and r["unit"] == "parameter"
    assert extract_impact("quantized into 16 4-bit centroids") == []


def test_thousands_separators_are_parsed():
    assert find(extract_impact("Built a 25,000+ row synthetic dataset"), 25000.0) is not None


# ---------------------------------------------------------------- rejection

@pytest.mark.parametrize("text", [
    "Fine-tuned LLaMA-2-7B with LoRA/QLoRA",          # model identifier
    "retaining accuracy on CIFAR-10",                  # dataset identifier
    "quantized into 16 4-bit centroids",               # design detail, not a result
    "Built an EEG-to-image pipeline using LSL markers",  # no numbers at all
    "Coordinator, Programming Club (Apr'24 - Mar'25)",   # dates
])
def test_non_results_are_rejected(text):
    assert extract_impact(text) == []


def test_years_are_never_results():
    assert extract_impact("Inter IIT Tech Meet in 2025 and 2026") == []


# ---------------------------------------------------------------- aggregation

RESUME = {
    "Work Experience": [
        {"organization": "Startup", "role": "AI Intern",
         "description": ["Cut p95 latency from 800 ms to 210 ms across 4,200 daily requests"]},
    ],
    "Projects": [
        {"title": "Compression", "organization": "EEA",
         "description": [
             "Reduced model size from 1051.5 KB to 75.6 KB while retaining 71.68% accuracy",
             "Built a from-scratch pipeline using pruning and Huffman coding",
         ]},
    ],
    "Position of Responsibility": [],
    "Major Competitions": [],
    "Research Experience": [],
    "Social Impact": [],
    "Scholastic Qualifications": ["Secured Rank 40 in WBJEE 2024 among 1.1 Lakh applicants"],
}


def test_aggregation_reports_the_quantified_ratio():
    out = extract_impact_signals(RESUME)
    assert out["total_bullets"] == 3
    # Two of the three bullets state a result; the third only describes the method.
    assert out["quantified_bullets"] == 2
    assert out["quantified_bullet_ratio"] == round(2 / 3, 3)
    assert "accuracy" in out["named_metrics"]
    assert out["by_section"]["Work Experience"] >= 1


def test_every_result_carries_its_source_bullet():
    """Required so the validation agent can trace each figure back to the PDF."""
    for r in extract_impact_signals(RESUME)["results"]:
        assert r["evidence"] and isinstance(r["evidence"], str)
        assert r["section"]


def test_scorer_publishes_impact_additively():
    from scorer_engine import extract_deterministic_signals
    resume = {**RESUME, "Department": "Electrical Engineering",
              "Academic Qualifications": []}
    s, _ = extract_deterministic_signals(resume, "", "SDE")
    assert "quantified_results" in s and "quantified_results_summary" in s
    # Additive: the original signals are untouched.
    assert "detected_analyst_firms" in s and "cpi_status" in s and "por_tier" in s
