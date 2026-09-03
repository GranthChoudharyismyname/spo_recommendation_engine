"""
Evidence floors — deterministic minimums for two pillars the qualitative evaluator scores.

The rubrics in `ROLE_RUBRICS` already state what the evidence is worth:

    "Tier-1 (18-20 pts): Top Analytics & Applied AI firms (...)"
    "Tier-2 (14-17 pts): Data analyst / BI / ML intern roles at high-growth startups"

When the recruiter knowledge graph independently confirms a company IS Tier-1 for the
target role, a floor of 18 does not override the rubric — it enforces it. Likewise the
role frameworks treat a quantified outcome as the EDGE dimension of SCOPE, so a resume
whose bullets consistently carry measured results should not be scored as if they did
not.

Three rules keep this safe:

  1. FLOORS ONLY. A floor never lowers a score. The evaluator may always score higher
     if it sees more than the deterministic evidence does.
  2. Floors are conservative — they sit at the BOTTOM of the rubric band the evidence
     justifies, never in the middle of it. They protect against under-crediting real
     evidence, not a way to inflate.
  3. Every application is recorded, with the evidence that triggered it, so any score
     movement is auditable and can be shown to the candidate.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Bottom of each rubric band. Deliberately the floor of the band, not its midpoint.
PEDIGREE_FLOOR = {1: 18, 2: 14, 3: 10}

# SCOPE floors keyed on the share of bullets that state a measured result. SCOPE covers
# more than numbers — scale, context, ownership, proof — so these sit well below the
# ceiling and only guard against a resume with dense measured evidence being read as
# unquantified.
SCOPE_FLOOR_BANDS: List[Tuple[float, int]] = [
    (0.60, 16),
    (0.35, 13),
]

MIN_BULLETS_FOR_SCOPE_FLOOR = 6

# Academics floors from the scholastic profile. Conservative on purpose: every IITK
# candidate cleared JEE Advanced, so only genuinely rare achievements move the floor.
# quant.txt §3 calls an international olympiad medal an "Instant Tier-1 shortlist across
# every quant firm" and lists national olympiad camp/podium alongside it.
SCHOLASTIC_FLOOR = {
    "outstanding": 17,
    "very_good": 15,
}

# CORE_TECHNOM folds SCOPE into a blended "Coursework & SCOPE" pillar, so a floor
# recorded against "SCOPE Articulation" would never match its pillar in the UI.
SCOPE_PILLAR_BY_TRACK = {"CORE_TECHNOM": "Coursework & SCOPE"}


def pedigree_floor(signals: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Work-experience floor from the best-tier firm the candidate has actually worked at,
    for the target role.

    The KG's two edges are not interchangeable. `pedigree_for` means "an internship here
    is a positive signal when applying for this role" — exactly this question — so it is
    preferred. It is populated for only 10 of 78 companies, so `recruits_for` is the
    fallback: a firm that recruits at Tier-1 for a role is credible Tier-1 pedigree for
    it. Which edge was used is recorded, and the two are never conflated in output.
    """
    firms = signals.get("kg_pedigree_firms") or []
    if not firms:
        return None

    best = min(firms, key=lambda f: (f.get("tier", 9), f.get("edge_type") != "pedigree_for"))
    tier = best.get("tier")
    floor = PEDIGREE_FLOOR.get(tier)
    if floor is None:
        return None

    return {
        "pillar": "Work Experience",
        "floor": floor,
        "reason": (
            f"{best['resolved_as']} is Tier-{tier} for this role in the recruiter knowledge "
            f"graph, and the rubric bands Tier-{tier} at {floor}-"
            f"{floor + (2 if tier == 1 else 3)} points."
        ),
        "evidence": {
            "organization": best.get("organization"),
            "resolved_as": best.get("resolved_as"),
            "tier": tier,
            "edge_type": best.get("edge_type"),
            # Recorded because pedigree_for is sparse and the fallback must be visible.
            "edge_is_fallback": best.get("edge_type") != "pedigree_for",
        },
    }


def scholastic_floor(signals: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Academics floor from the scholastic profile.

    The Scholastic Achievements section is where olympiad stage, entrance rank and
    fellowships live, and the frameworks treat the top of that range as decisive. A
    diluting entry never lowers anything — it is surfaced as advice instead.
    """
    summary = signals.get("scholastic_summary")
    if not summary:
        return None
    tier = summary.get("strongest_tier")
    floor = SCHOLASTIC_FLOOR.get(tier)
    if floor is None:
        return None

    detail = signals.get("scholastic_signals") or []
    best = next((s for s in detail if s.get("tier") == tier), None)

    return {
        "pillar": "Academics & CPI",
        "floor": floor,
        "reason": (
            f"The scholastic profile reaches the {tier.replace('_', ' ')} band. "
            + (best.get("basis", "") if best else "")
        ).strip(),
        "evidence": {
            "strongest_tier": tier,
            "olympiad_stage": summary.get("olympiad_stage"),
            "by_tier": summary.get("by_tier"),
            "example": (best or {}).get("evidence"),
        },
    }


def scope_floor(signals: Dict[str, Any], track: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """SCOPE floor from the share of bullets carrying a measured result."""
    summary = signals.get("quantified_results_summary")
    if not summary:
        return None

    total = summary.get("total_bullets") or 0
    if total < MIN_BULLETS_FOR_SCOPE_FLOOR:
        # Too few bullets for a ratio to mean anything.
        return None

    ratio = summary.get("quantified_bullet_ratio") or 0.0
    for threshold, floor in SCOPE_FLOOR_BANDS:
        if ratio >= threshold:
            return {
                # CORE_TECHNOM blends SCOPE into "Coursework & SCOPE"; naming the wrong
                # pillar would leave the adjustment invisible on that track.
                "pillar": SCOPE_PILLAR_BY_TRACK.get(track or "", "SCOPE Articulation"),
                "floor": floor,
                "reason": (
                    f"{summary['quantified_bullets']} of {total} bullets state a measured "
                    f"result ({ratio:.0%}), across {summary['total']} figures."
                ),
                "evidence": {
                    "quantified_bullets": summary["quantified_bullets"],
                    "total_bullets": total,
                    "ratio": ratio,
                    "named_metrics": summary.get("named_metrics", []),
                },
            }
    return None


def apply_floors(
    *,
    work_experience_score: int,
    scope_score: int,
    signals: Dict[str, Any],
    academics_score: Optional[int] = None,
    track: Optional[str] = None,
) -> Tuple[int, int, Optional[int], List[Dict[str, Any]]]:
    """
    Returns (work_experience, scope, academics, adjustments).

    `academics_score` is optional because it is a deterministic pillar the scorer already
    computes; pass it to let a scholastic floor apply, omit it to leave it alone.

    An adjustment is recorded only when a floor actually raised a score, so the log is a
    record of what changed rather than of what was considered.
    """
    adjustments: List[Dict[str, Any]] = []

    candidates = [
        (work_experience_score, pedigree_floor(signals), "work_experience"),
        (scope_score, scope_floor(signals, track), "scope"),
    ]
    if academics_score is not None:
        candidates.append((academics_score, scholastic_floor(signals), "academics"))

    for current, candidate, field in candidates:
        if candidate is None or current is None:
            continue
        if candidate["floor"] > current:
            adjustments.append({
                **candidate, "from": current, "to": candidate["floor"], "field": field,
            })

    for adj in adjustments:
        if adj["field"] == "work_experience":
            work_experience_score = adj["to"]
        elif adj["field"] == "scope":
            scope_score = adj["to"]
        else:
            academics_score = adj["to"]

    return work_experience_score, scope_score, academics_score, adjustments
