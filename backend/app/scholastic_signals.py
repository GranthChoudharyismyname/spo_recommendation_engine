"""
Scholastic achievement extraction.

The Scholastic Achievements section carries some of the strongest signals on an IITK
resume — olympiad stage, entrance rank, fellowships, institute awards — and the
deterministic layer was detecting almost none of it. `has_olympiad` was a single boolean
matching nine acronyms, so a state-level qualifier and an international medal scored
identically, and IOQM, NSEP, NSEC, WBJEE, NEET and admission offers were invisible.

Tiers are taken from the role frameworks, not invented:

  quant.txt §3         "International Olympiad Medalists: IMO, IOI, IPhO — Instant Tier-1"
                       "National Olympiad Camp/Podium: INMO, INOI, INPhO, KVPY Top 50"
  quant.txt §2.1        JEE Advanced AIR bands: <200, <500, 500-1000, >1500 omit
  consult_pm.txt §2.A   "top 0.25 percentile" Outstanding, "top 0.5 percentile" Very Good,
                        "top 2-3%" DILUTES

That last rule matters as much as the others: the frameworks are explicit that a weak
rank listed beside a strong one hurts, so weak ranks are reported as diluting rather
than quietly ignored.

Deterministic, and published as an additive hard signal so it reaches the qualitative
evaluator's prompt.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

TIER_OUTSTANDING = "outstanding"
TIER_VERY_GOOD = "very_good"
TIER_GOOD = "good"
TIER_DILUTING = "negative_diluting"

# ---------------------------------------------------------------- olympiads
# Stage order matters: an international medal outranks a national camp, which outranks a
# national paper, which outranks a screening exam.
OLYMPIAD_STAGES: List[Tuple[str, List[str]]] = [
    ("international", [
        r"\bIMO\b", r"\bIOI\b", r"\bIPhO\b", r"\bIChO\b", r"\bIBO\b", r"\bIOAA\b",
        r"\bIAO\b", r"\bIJSO\b",
        r"International\s+\w*\s*Olympiad",
    ]),
    ("camp", [
        r"\bOCSC\b", r"\bIMOTC\b", r"Orientation\s*cum\s*Selection\s*Camp",
        r"Training\s*Camp",
    ]),
    ("national", [
        r"\bINMO\b", r"\bINPhO\b", r"\bINChO\b", r"\bINBO\b", r"\bINAO\b", r"\bINJSO\b",
        r"\bINOI\b",
        r"Indian\s+National\s+\w*\s*Olympiad",
    ]),
    ("qualifier", [
        r"\bIOQM\b", r"\bIOQP\b", r"\bIOQC\b", r"\bIOQJS\b", r"\bIOQA\b",
        r"\bNSEP\b", r"\bNSEC\b", r"\bNSEB\b", r"\bNSEA\b", r"\bNSEJS\b", r"\bRMO\b",
        r"Indian\s+Olympiad\s+Qualifier", r"National\s+Standard\s+Examination",
    ]),
]

STAGE_TIER = {
    "international": TIER_OUTSTANDING,
    "camp": TIER_OUTSTANDING,
    "national": TIER_VERY_GOOD,
    "qualifier": TIER_GOOD,
}

_MEDAL = re.compile(r"\b(?:gold|silver|bronze)\s*medal|\bmedal(?:list|ist)\b", re.IGNORECASE)

# ---------------------------------------------------------------- entrance exams
ENTRANCE_EXAMS: List[Tuple[str, str]] = [
    ("JEE Advanced", r"JEE\s*\(?\s*Advanced\s*\)?"),
    ("JEE Main", r"JEE\s*\(?\s*Main[s]?\s*\)?"),
    ("KVPY", r"\bKVPY\b"),
    ("NEET", r"\bNEET\b"),
    ("GATE", r"\bGATE\b"),
    ("BITSAT", r"\bBITSAT\b"),
    ("WBJEE", r"\bWBJEE\b"),
    ("MHT-CET", r"\bMHT[- ]?CET\b"),
    ("KCET", r"\bKCET\b"),
    ("COMEDK", r"\bCOMEDK\b"),
    ("State entrance", r"\b[A-Z]{2,6}\s*CET\b|\bstate\s+(?:joint\s+)?entrance\b"),
]

_RANK = re.compile(
    r"(?:All\s*India\s*Rank|AIR|Rank|Position)\s*[:\-]?\s*(\d{1,7})"
    r"|(?:secured|obtained|achieved|scored)\s+(?:an?\s+)?(?:AIR|rank)\s*[:\-]?\s*(\d{1,7})",
    re.IGNORECASE,
)
_COHORT = re.compile(
    r"(?:among|out\s*of|amongst|from|across)\s*(?:over\s*)?"
    r"([\d,.]+)\s*(lakh|lakhs|crore|k|million|thousand)?",
    re.IGNORECASE,
)
_MAGNITUDE = {"lakh": 100_000, "lakhs": 100_000, "crore": 10_000_000,
              "k": 1_000, "thousand": 1_000, "million": 1_000_000}

# quant.txt §2.1 — JEE Advanced AIR bands, verbatim thresholds.
JEE_ADV_BANDS = [(200, TIER_OUTSTANDING), (500, TIER_VERY_GOOD), (1000, TIER_GOOD)]
JEE_ADV_OMIT_ABOVE = 1500

# consult_pm.txt §2.A — percentile bands for any national ranker.
PERCENTILE_OUTSTANDING = 0.0025
PERCENTILE_VERY_GOOD = 0.005
PERCENTILE_DILUTING = 0.02

# ---------------------------------------------------------------- awards
AWARDS: List[Tuple[str, str, str]] = [
    (r"Academic\s*Excellence\s*Award|\bAEA\b", "Academic Excellence Award", TIER_VERY_GOOD),
    (r"\bKVPY\b[^.]{0,40}\b(?:fellow|fellowship|SA|SB|SX)\b", "KVPY fellowship", TIER_VERY_GOOD),
    (r"\bINSPIRE\b", "INSPIRE scholarship", TIER_GOOD),
    (r"\bNTSE\b", "NTSE scholar", TIER_VERY_GOOD),
    (r"Quadeye\s*Excellence|AlphaGrep\s*Scholarship|OPJEMS|Aditya\s*Birla|O\.?P\.?\s*Jindal|"
     r"Class\s*of\s*1990\s*Scholarship|Optiver\s*Future\s*Focus",
     "Named corporate scholarship", TIER_OUTSTANDING),
    (r"\bSURGE\b|\bMITACS\b|\bDAAD\s*WISE\b|\bCharpak\b",
     "Competitive research fellowship", TIER_OUTSTANDING),
    (r"Dean'?s\s*(?:List|Honou?r)", "Dean's list", TIER_VERY_GOOD),
    (r"(?:admission|offer)\s*letter[^.]{0,50}\b(?:IISc|MIT|Stanford|Cambridge|Oxford|ETH)\b"
     r"|\b(?:IISc|MIT|Stanford)\b[^.]{0,40}(?:admission|offer)",
     "Competitive admission offer", TIER_VERY_GOOD),
]

TIER_RANK = {TIER_OUTSTANDING: 3, TIER_VERY_GOOD: 2, TIER_GOOD: 1, TIER_DILUTING: 0}


def _parse_cohort(text: str, after: int) -> Optional[int]:
    m = _COHORT.search(text[after: after + 90])
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = (m.group(2) or "").lower().strip()
    if unit in _MAGNITUDE:
        value *= _MAGNITUDE[unit]
    return int(value) if value >= 100 else None


def _olympiad_stage(line: str) -> Optional[str]:
    for stage, patterns in OLYMPIAD_STAGES:
        for pattern in patterns:
            if re.search(pattern, line, re.IGNORECASE):
                return stage
    return None


def _classify_rank(exam: str, rank: int, cohort: Optional[int]) -> Tuple[str, str]:
    """(tier, basis), grounded in the framework bands rather than invented."""
    if exam == "JEE Advanced":
        for threshold, tier in JEE_ADV_BANDS:
            if rank <= threshold:
                return tier, f"quant.txt §2.1 — JEE Advanced AIR under {threshold}"
        if rank > JEE_ADV_OMIT_ABOVE:
            return TIER_DILUTING, (
                f"quant.txt §2.1 — AIR above {JEE_ADV_OMIT_ABOVE}; the framework advises "
                "omitting it rather than inviting negative comparison"
            )
        return TIER_GOOD, "quant.txt §2.1 — JEE Advanced AIR in the conditional band"

    if cohort:
        percentile = rank / cohort
        if percentile <= PERCENTILE_OUTSTANDING:
            return TIER_OUTSTANDING, (
                f"consult_pm.txt §2.A — top {percentile:.3%} of {cohort:,}, inside the "
                "top 0.25 percentile band"
            )
        if percentile <= PERCENTILE_VERY_GOOD:
            return TIER_VERY_GOOD, (
                f"consult_pm.txt §2.A — top {percentile:.2%} of {cohort:,}, inside the "
                "top 0.5 percentile band"
            )
        if percentile >= PERCENTILE_DILUTING:
            return TIER_DILUTING, (
                f"consult_pm.txt §2.A — top {percentile:.1%} only; the framework lists "
                "moderate rankers as diluting"
            )
        return TIER_GOOD, f"top {percentile:.2%} of {cohort:,}"

    if rank <= 100:
        return TIER_VERY_GOOD, "rank under 100, cohort size not stated"
    return TIER_GOOD, "rank stated without a cohort size, so the percentile is unknown"


def extract_from_line(line: str) -> List[Dict[str, Any]]:
    """Scholastic signals in one achievement line."""
    out: List[Dict[str, Any]] = []
    text = (line or "").strip()
    if not text:
        return out

    stage = _olympiad_stage(text)
    if stage:
        tier = STAGE_TIER[stage]
        medal = bool(_MEDAL.search(text))
        if medal and stage in ("international", "national"):
            tier = TIER_OUTSTANDING
        out.append({
            "kind": "olympiad", "stage": stage, "tier": tier, "medal": medal,
            "evidence": text,
            "basis": ("quant.txt §3 — International Olympiad Medalists / National Olympiad Camp"
                      if tier == TIER_OUTSTANDING else f"olympiad {stage} stage"),
        })

    # A single line often names two exams — "642/720 in NEET and Rank 40 in WBJEE" — so
    # each rank binds to the NEAREST exam mention rather than the first one in list order.
    exam_positions: List[Tuple[str, int]] = []
    for exam, pattern in ENTRANCE_EXAMS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            exam_positions.append((exam, m.start()))

    seen_exams = set()
    for rank_match in _RANK.finditer(text):
        rank = int(next(g for g in rank_match.groups() if g))
        # Distance is measured from the NUMBER, not the start of the whole phrase:
        # "secured Rank 40 in WBJEE" starts nearer NEET earlier in the line, but the 40
        # plainly belongs to WBJEE. The common Indian phrasing puts the exam after the
        # rank, so an exam within 25 characters downstream wins outright.
        digits = rank_match.start() + rank_match.group(0).rfind(str(rank))
        nearest = None
        if exam_positions:
            following = [(e, pos) for e, pos in exam_positions if 0 <= pos - digits <= 25]
            pool = following or exam_positions
            nearest, _ = min(pool, key=lambda pair: abs(pair[1] - digits))

        cohort = _parse_cohort(text, rank_match.end())

        # A rank with no named exam is still a signal when a cohort is stated, because
        # the percentile — which is what the framework bands actually use — is computable.
        if nearest is None and cohort is None:
            continue
        if nearest and nearest in seen_exams:
            continue
        if nearest:
            seen_exams.add(nearest)

        tier, basis = _classify_rank(nearest or "", rank, cohort)
        out.append({
            "kind": "entrance_rank", "exam": nearest, "rank": rank, "cohort": cohort,
            "percentile": round(rank / cohort, 6) if cohort else None,
            "tier": tier, "evidence": text, "basis": basis,
        })

    for pattern, label, tier in AWARDS:
        if re.search(pattern, text, re.IGNORECASE):
            out.append({
                "kind": "award", "award": label, "tier": tier, "evidence": text,
                "basis": "institute or national award",
            })
            break
    return out


def extract_scholastic_signals(resume_json: Dict[str, Any], raw_text: str = "") -> Dict[str, Any]:
    """
    Every scholastic signal on the resume, tiered against the role frameworks.

    Scoped to the Scholastic Qualifications section, matching the existing engine's
    discipline of not sweeping the whole document; raw text is a fallback only when that
    section is empty.
    """
    lines = [l for l in (resume_json.get("Scholastic Qualifications") or []) if isinstance(l, str)]
    if not lines and raw_text:
        lines = [l.strip() for l in raw_text.splitlines() if len(l.strip()) > 20][:40]

    signals: List[Dict[str, Any]] = []
    for line in lines:
        signals.extend(extract_from_line(line))

    by_tier: Dict[str, int] = {}
    for s in signals:
        by_tier[s["tier"]] = by_tier.get(s["tier"], 0) + 1

    strongest = max(
        (s for s in signals if s["tier"] != TIER_DILUTING),
        key=lambda s: TIER_RANK[s["tier"]], default=None,
    )

    return {
        "signals": signals,
        "total": len(signals),
        "by_tier": by_tier,
        "strongest_tier": strongest["tier"] if strongest else None,
        "strongest": strongest,
        # Surfaced rather than dropped: the frameworks are explicit that a weak rank
        # beside a strong one dilutes.
        "diluting": [s for s in signals if s["tier"] == TIER_DILUTING],
        "olympiad_stage": next((s["stage"] for s in signals if s["kind"] == "olympiad"), None),
    }
