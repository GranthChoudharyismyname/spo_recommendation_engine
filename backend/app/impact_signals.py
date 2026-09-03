"""
Quantified-impact extraction.

The numeric results in a resume are the signal that separates "described the work" from
"showed what the work achieved". The corpora encode them in a fixed shape:

    {"metric": "latency", "direction": "decrease", "value": 3.0, "unit": "x"}

This module produces that same shape from a live resume, so extracted impact stays
directly comparable with the corpora the rubrics were calibrated against.

It is deterministic and additive. Results are published as a hard signal, which means
they reach the qualitative evaluator through the existing HARD SIGNALS prompt block
without any change to the prompt, and the validation agent can trace every one of them
back to the source text.

Nothing here scores. It reports what was measured and where.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# Units, longest-first so "percent" wins over "per" and "ms" over "m".
_UNIT_PATTERNS: List[tuple] = [
    (r"%|percent(?:age)?|pc\b", "percent"),
    (r"×|\bx\b(?=\s|$|[,.;])", "x"),
    (r"\bbps\b", "bps"),
    (r"\bns\b", "nanoseconds"),
    (r"µs|\bus\b", "microseconds"),
    (r"\bms\b", "milliseconds"),
    (r"\bsec(?:onds?)?\b|\bs\b(?=\s|$|[,.;])", "seconds"),
    (r"\bmin(?:ute)?s?\b", "minutes"),
    (r"\bhours?\b|\bhrs?\b", "hours"),
    (r"\bdays?\b", "days"),
    (r"\b[kmgt]b\b", "bytes"),
    (r"\bqps\b|\brps\b|\bfps\b", "per_second"),
    (r"\blakh\b|\bcrore\b|\bcr\b", "indian_scale"),
    (r"₹|\brs\.?\b|\binr\b", "rupees"),
    (r"\$|\busd\b", "dollars"),
]

# Metric nouns worth naming. Ordered so a specific term beats a generic one.
_METRIC_TERMS = [
    "macro-f1", "micro-f1", "f1 score", "f1", "roc-auc", "auc", "accuracy", "precision",
    "recall", "bleu4", "bleu", "rouge", "map", "miou", "rmse", "mae", "mape", "r2",
    "mean squared error", "mse", "perplexity", "sharpe", "drawdown", "cagr",
    "latency", "throughput", "compression", "speedup", "bandwidth", "memory", "model size",
    "parameters", "conversion", "retention", "churn", "revenue", "cost", "savings",
    "uptime", "coverage", "error rate", "win rate", "click-through", "engagement",
    "team size", "budget", "footfall", "participants", "users", "downloads",
]

_DIRECTION_TERMS = [
    (r"\b(?:reduc\w*|cut\w*|lower\w*|decreas\w*|shrank|shrunk|minimis\w*|minimiz\w*|down\s+to|from\s+[\d.]+\s*\w*\s*(?:to|→|->))\b", "decrease"),
    (r"\b(?:increas\w*|improv\w*|boost\w*|rais\w*|grew|grow\w*|scal\w*\s+to|up\s+to|gain\w*|uplift)\b", "increase"),
    (r"\b(?:top|among\s+the\s+top|rank\w*|position|placed)\b", "top"),
    (r"\b(?:achiev\w*|reach\w*|attain\w*|scor\w*|secur\w*|met|hit)\b", "achieved"),
]

# A number with an optional magnitude suffix, e.g. 13.9, 268.6K, 1,100, 12M.
_NUMBER = re.compile(
    r"(?<![\w.])"
    r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
    r"\s*"
    r"([kmb]\b|lakh\b|crore\b|cr\b)?",
    re.IGNORECASE,
)

_MAGNITUDE = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000,
              "lakh": 100_000, "crore": 10_000_000, "cr": 10_000_000}

# Numbers that are dates or version strings, not results.
_NOISE_YEAR = re.compile(r"^(?:19|20)\d{2}$")


def _find_unit(after: str) -> Optional[str]:
    """The unit immediately following a number, if any."""
    window = after[:14].lower()
    for pattern, name in _UNIT_PATTERNS:
        m = re.match(r"\s*(?:" + pattern + r")", window, re.IGNORECASE)
        if m:
            return name
    return None


def _find_metric(sentence: str, position: int) -> Optional[str]:
    """
    The metric noun NEAREST the number, not the longest one in the window.

    Picking the longest match mislabels a bullet that names several metrics: in
    "Reduced model size from 1051.5 KB ... while retaining 71.68% accuracy", the 71.68
    belongs to accuracy, but "model size" is the longer term and would win.
    """
    lower = sentence.lower()
    best: Optional[str] = None
    best_distance = 10 ** 6

    for term in _METRIC_TERMS:
        for m in re.finditer(re.escape(term), lower):
            # Distance from the number to the nearest edge of the term.
            if m.end() <= position:
                distance = position - m.end()
            elif m.start() >= position:
                distance = m.start() - position
            else:
                distance = 0
            if distance > 90:
                continue
            # A metric stated after the number ("71.68% accuracy") binds more tightly
            # than one stated before it, so break ties in its favour.
            adjusted = distance - (6 if m.start() >= position else 0)
            if adjusted < best_distance or (adjusted == best_distance and len(term) > len(best or "")):
                best, best_distance = term, adjusted
    return best


def _metric_distance(sentence: str, position: int, term: str) -> int:
    """Characters between the number and the nearest occurrence of `term`."""
    lower = sentence.lower()
    best = 10 ** 6
    for m in re.finditer(re.escape(term), lower):
        if m.end() <= position:
            best = min(best, position - m.end())
        elif m.start() >= position:
            best = min(best, m.start() - position)
        else:
            return 0
    return best


def _metric_is_adjacent(sentence: str, position: int, window: int = 28) -> bool:
    """A named metric bound to this number by proximity or an explicit = / : separator."""
    lower = sentence.lower()
    near = lower[max(0, position - window): position + window]
    if not any(t in near for t in _METRIC_TERMS):
        return False
    before = lower[max(0, position - 6): position]
    return bool(re.search(r"[=:]\s*$", before)) or any(
        t in lower[max(0, position - window): position] or
        t in lower[position: position + window]
        for t in _METRIC_TERMS
    )


# A trailing count-noun becomes the unit, matching how the corpora record
# {"metric": "team size", "value": 30, "unit": "secretaries"}.
_COUNT_NOUN = re.compile(
    r"[+~]?\s*([a-z][a-z-]{2,20}(?:s|es)?)\b", re.IGNORECASE
)
_NOT_A_UNIT = {
    "and", "the", "with", "from", "into", "over", "using", "for", "across", "via", "per",
    "while", "then", "that", "this", "which", "after", "before", "under", "above",
    "tier", "part", "based", "point", "step", "stage", "time", "times", "fold",
    # adjectives that precede the real noun
    "daily", "weekly", "monthly", "annual", "yearly", "total", "unique", "distinct",
    "raw", "new", "different", "separate", "synthetic", "real", "live", "active",
}


def _find_count_noun(after: str) -> Optional[str]:
    m = _COUNT_NOUN.match(after)
    if not m:
        return None
    word = m.group(1).lower()
    return None if word in _NOT_A_UNIT else word


def _find_direction(sentence: str, position: int) -> Optional[str]:
    """Whether the number is framed as a reduction, a gain, a rank, or a bare result."""
    lower = sentence.lower()
    lo = max(0, position - 50)
    window = lower[lo: position + 30]
    best, best_distance = None, 10 ** 6
    for pattern, name in _DIRECTION_TERMS:
        for m in re.finditer(pattern, window, re.IGNORECASE):
            distance = abs((lo + m.end()) - position)
            if distance < best_distance:
                best, best_distance = name, distance
    return best


# A number glued into an identifier is not a result: CIFAR-10, LLaMA-2-7B, 4-bit,
# 2-tier, GPT-4. The tell is a hyphen immediately before whose preceding run contains a
# letter — "LLaMA-2-7B" reaches back past the "2" to find "LLaMA". Note 7B there is a
# real parameter count, but it names the model, not the candidate's measured outcome.
_IDENTIFIER_RUN = re.compile(r"([A-Za-z0-9.]+(?:-[A-Za-z0-9.]+)*)-$")
_IDENTIFIER_AFTER = re.compile(r"^-[A-Za-z]")


def _inside_identifier(sentence: str, position: int) -> bool:
    m = _IDENTIFIER_RUN.search(sentence[max(0, position - 30): position])
    return bool(m) and any(ch.isalpha() for ch in m.group(1))

# Directions strong enough to make a bare number a result on their own.
_STRONG_DIRECTIONS = {"decrease", "increase", "top"}

# Units that denote a measured quantity rather than a counted thing.
_MEASURED_UNITS = {
    "percent", "x", "bps", "nanoseconds", "microseconds", "milliseconds", "seconds",
    "minutes", "hours", "days", "bytes", "per_second", "rupees", "dollars", "indian_scale",
}

METRIC_PROXIMITY = 45
COUNT_METRIC_PROXIMITY = 20

# "Grounding = 0.57", "BLEU4 = 0.79", "Sharpe: 1.8". The label names the metric, whether
# or not it is in _METRIC_TERMS — which is what makes this work on metrics we have never
# seen. Captured as 1-3 words immediately before the separator.
_LABELLED_VALUE = re.compile(
    r"([A-Za-z][A-Za-z0-9]*(?:[ -][A-Za-z][A-Za-z0-9]*){0,2})\s*[=:]\s*$"
)


# Words that make a captured label a sentence fragment rather than a metric name:
# "Met all five KPIs: 99.7%" must not report the metric as "all five kpis".
_LABEL_STOPWORDS = {
    "and", "or", "the", "a", "an", "of", "in", "on", "with", "for", "to", "at", "by",
    "met", "all", "both", "each", "every", "some", "these", "those", "including",
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "scores", "score", "results", "result", "kpis", "kpi", "metrics", "values",
}


def _labelled_metric(sentence: str, position: int) -> Optional[str]:
    m = _LABELLED_VALUE.search(sentence[max(0, position - 40): position])
    if not m:
        return None
    words = m.group(1).strip().lower().split()
    # Drop leading conjunctions and quantifiers: "and Numeric VQA" -> "numeric vqa".
    while words and words[0] in _LABEL_STOPWORDS:
        words.pop(0)
    # If nothing survives, or every word was filler, this is not a metric name.
    if not words or all(w in _LABEL_STOPWORDS for w in words):
        return None
    label = " ".join(words)
    return label if 1 <= len(label) <= 40 else None


def extract_impact(text: str) -> List[Dict[str, Any]]:
    """Quantified results in one bullet, in the corpora's `impact` shape."""
    out: List[Dict[str, Any]] = []
    seen = set()

    for match in _NUMBER.finditer(text):
        raw, suffix = match.group(1), (match.group(2) or "").lower().strip()
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue

        # --- reject identifiers and dates outright
        if _inside_identifier(text, match.start()):
            continue
        if _NOISE_YEAR.match(raw):
            continue

        # A hyphenated word after the number usually makes it an adjective — "4-bit",
        # "2-tier" — but not when a magnitude suffix is present: "268.6K-parameter" is a
        # scale figure, and the hyphenated word is its unit.
        hyphen_suffix = _IDENTIFIER_AFTER.match(text[match.end(): match.end() + 2])
        if hyphen_suffix and not suffix:
            continue

        unit = _find_unit(text[match.end():])
        if suffix in _MAGNITUDE:
            value *= _MAGNITUDE[suffix]
        if unit is None and hyphen_suffix:
            noun = re.match(r"-([a-z][a-z-]{2,20})", text[match.end():], re.IGNORECASE)
            if noun and noun.group(1).lower() not in _NOT_A_UNIT:
                unit = noun.group(1).lower()

        counted = False
        if unit is None and not suffix:
            noun = _find_count_noun(text[match.end():])
            if noun:
                unit, counted = noun, True

        # An explicit label binds tightest and needs no vocabulary.
        metric = _labelled_metric(text, match.start()) or _find_metric(text, match.start())
        direction = _find_direction(text, match.start())

        # A metric far from the number is describing a different figure in the same
        # sentence, so drop it rather than mislabel.
        #
        # A number carrying a MEASURED unit (ms, %, ×) is a reading, and a metric name
        # some distance away is plausibly still its own: "cut latency from 4.1 s to
        # 900 ms". A number carrying only a scale — 12M events, a 40M-key workload — is
        # sizing the work, not reporting a metric, so a distant name almost certainly
        # belongs to a different figure and must not attach.
        scale_only = unit not in _MEASURED_UNITS
        limit = COUNT_METRIC_PROXIMITY if (counted or scale_only) else METRIC_PROXIMITY
        if metric and _metric_distance(text, match.start(), metric) > limit:
            metric = None

        # --- acceptance. A number is a RESULT when it is measured, counted at scale,
        # bound to a named metric, or explicitly framed as a gain, cut or rank.
        measured = unit in _MEASURED_UNITS
        counted_at_scale = counted and value >= 10
        # A magnitude suffix is a scale statement on its own: "12M daily events",
        # "25K rows", "1.4 Lakh". No other anchor is needed.
        at_magnitude = bool(suffix)
        metric_bound = bool(_labelled_metric(text, match.start())) or _metric_is_adjacent(text, match.start())
        directed = direction in _STRONG_DIRECTIONS and (unit is not None or bool(suffix))

        if not (measured or counted_at_scale or at_magnitude or metric_bound or directed):
            continue

        key = (metric, direction, value, unit)
        if key in seen:
            continue
        seen.add(key)

        out.append({
            "metric": metric,
            "direction": direction,
            "value": value,
            "unit": unit,
            # Kept so the validation layer can trace it and the UI can quote it.
            "evidence": text.strip(),
        })
    return out


_SECTIONS = [
    ("Work Experience", "role"),
    ("Projects", "title"),
    ("Research Experience", "title"),
    ("Major Competitions", "competition"),
    ("Position of Responsibility", "position"),
    ("Social Impact", "role"),
]


def extract_impact_signals(resume_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Every quantified result in the resume, grouped by section.

    Returned as a hard signal so it reaches the qualitative evaluator's HARD SIGNALS
    context. The evaluator scores SCOPE articulation and work-experience impact; telling
    it exactly which figures the candidate actually reported makes that judgement
    grounded rather than impressionistic.
    """
    results: List[Dict[str, Any]] = []

    for section, title_key in _SECTIONS:
        for entry in resume_json.get(section) or []:
            if not isinstance(entry, dict):
                continue
            heading = str(entry.get(title_key) or entry.get("organization") or "").strip()
            for bullet in entry.get("description") or []:
                for impact in extract_impact(str(bullet)):
                    results.append({**impact, "section": section, "entry": heading})

    # Scholastic lines are strings, not entries, and carry rank/percentile results.
    for line in resume_json.get("Scholastic Qualifications") or []:
        if isinstance(line, str):
            for impact in extract_impact(line):
                results.append({**impact, "section": "Scholastic Qualifications", "entry": ""})

    by_section: Dict[str, int] = {}
    for r in results:
        by_section[r["section"]] = by_section.get(r["section"], 0) + 1

    # Bullets that state a result versus bullets that only describe activity. This is the
    # ratio the SCOPE pillar is really measuring.
    total_bullets = 0
    for section, _ in _SECTIONS:
        for entry in resume_json.get(section) or []:
            if isinstance(entry, dict):
                total_bullets += len(entry.get("description") or [])
    quantified_bullets = len({r["evidence"] for r in results if r["section"] != "Scholastic Qualifications"})

    return {
        "results": results,
        "total": len(results),
        "by_section": by_section,
        "quantified_bullets": quantified_bullets,
        "total_bullets": total_bullets,
        "quantified_bullet_ratio": (
            round(quantified_bullets / total_bullets, 3) if total_bullets else 0.0
        ),
        "named_metrics": sorted({r["metric"] for r in results if r["metric"]}),
    }
