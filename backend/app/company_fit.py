"""
Estimated Shortlist Fit.

This is a directional estimate, not a hiring prediction, and the response says so.
It is built from two identified sources and nothing else:

  1. The curated recruiter knowledge graph (`companies.seed.json`) supplies which firms
     recruit for the selected track at IITK and at what tier. Firms whose
     `recruiting_mode` is PPO_DOMINANT are excluded, because for those the campus
     channel effectively does not exist — an empty panel there is correct behaviour.
  2. The scoring engine's own published verdict thresholds supply the tier bars.
     `scorer_engine.score_resume` calls 80+ "Outstanding (Strong Shortlist Contender)"
     and 70+ "Very Good (Shortlist Contender)"; those two numbers are the Tier-1 and
     Tier-2 bars used here. No other constant is introduced.

The mapping from (composite score - tier bar) to a percentage is a logistic with a
fixed slope. It is calibrated against nothing, which is exactly why the API labels it
`model_version: "kg-tier-heuristic-v0"` and carries an explicit disclosure.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from kg_adapter import load_kg
from tracks import get_track

# scorer_engine.score_resume verdict thresholds.
TIER_BARS = {1: 80.0, 2: 70.0, 3: 58.0, 4: 58.0}
LOGISTIC_SLOPE = 6.0

BAND_STRONG = "Strong"
BAND_COMPETITIVE = "Competitive"
BAND_STRETCH = "Stretch"

MODEL_VERSION = "kg-tier-heuristic-v0"
DISCLOSURE = (
    "Directional estimate based on resume signals and the selected role; not an employer "
    "prediction. Derived from curated recruiter tiers and this engine's own verdict thresholds."
)

CATEGORY_LABELS = {
    "PROP_TRADING": "Proprietary trading",
    "TECH_PRODUCT": "Product technology",
    "TECH_STARTUP": "High-growth technology",
    "CONSULTING": "Management consulting",
    "ENERGY_OIL": "Energy and hydrocarbons",
    "SEMICONDUCTOR": "Semiconductors",
    "BANKING": "Banking",
    "IB_MARKETS": "Investment banking and markets",
    "FMCG": "FMCG",
    "MANUFACTURING": "Manufacturing",
    "AUTOMOTIVE": "Automotive",
    "ANALYTICS_SERVICES": "Analytics services",
}


def _fit_percentage(overall_score: float, tier: int) -> int:
    bar = TIER_BARS.get(tier, 58.0)
    value = 100.0 / (1.0 + math.exp(-(overall_score - bar) / LOGISTIC_SLOPE))
    return int(round(max(3.0, min(97.0, value))))


def _band(fit: int) -> str:
    if fit >= 65:
        return BAND_STRONG
    if fit >= 40:
        return BAND_COMPETITIVE
    return BAND_STRETCH


def _driving_pillar(pillars: Dict[str, Any], weights: Dict[str, float]) -> Optional[str]:
    """The pillar contributing the most weighted deficit — the one to name in the rationale."""
    ranked = []
    for name, entry in (pillars or {}).items():
        if not isinstance(entry, dict):
            continue
        score = entry.get("score")
        if not isinstance(score, (int, float)):
            continue
        weight = weights.get(name)
        if weight is None:
            weight = weights.get("Projects & Depth", 0.0) if name.startswith(("Projects", "Core Projects")) else 0.0
        ranked.append((weight * (20 - score), name, score, weight))
    if not ranked:
        return None
    ranked.sort(reverse=True)
    _, name, score, weight = ranked[0]
    return f"{name} at {score:.0f}/20 carries {weight:.0%} of this track's content weight."


def build_company_fit(
    overall_score: float,
    track: str,
    pillars: Dict[str, Any],
    weights: Dict[str, float],
    branch: Optional[str] = None,
    limit: int = 12,
) -> Dict[str, Any]:
    """
    Compose the Estimated Shortlist Fit panel.

    Ranking lives in `kg_adapter.match_recruiters`, where the graph data is — this
    function only composes the panel around it. Previously the fit percentage depended
    on the composite score alone, so every Tier-1 firm scored identically and the five
    shown were effectively arbitrary; ranking now uses observed IITK recruiting and
    per-firm branch history, so the order actually responds to the candidate.
    """
    kg = load_kg()
    if kg is None:
        return {
            "available": False,
            "reason": "Recruiter knowledge graph not found; shortlist fit cannot be derived.",
            "entries": [], "model_version": MODEL_VERSION, "disclosure": DISCLOSURE,
        }

    matches = kg.match_recruiters(
        track=track, overall_score=overall_score, branch=branch,
        tier_bars=TIER_BARS, limit=limit,
    )
    if not matches:
        return {
            "available": False,
            "reason": f"No campus-channel recruiters are curated for {track}.",
            "entries": [], "model_version": MODEL_VERSION, "disclosure": DISCLOSURE,
        }

    role = get_track(track).kg_role
    excluded = sum(
        1 for c in kg.companies
        if (c.get("recruits_for") or {}).get(role)
        and (c.get("recruiting_mode") == "PPO_DOMINANT"
             or c.get("iitk_presence") == "ppo_only_expected")
    )
    pool = len(kg.match_recruiters(track=track, overall_score=overall_score, branch=branch))
    driver = _driving_pillar(pillars, weights)

    entries = [{
        "company": m.display_name,
        "company_id": m.company_id,
        "category": CATEGORY_LABELS.get(m.category, m.category.replace("_", " ").title()),
        "tier": m.tier,
        "tier_label": m.tier_label,
        "fit_score": m.fit,
        "fit_band": m.band,
        "rationale": m.rationale,
        "recruiting_mode": m.recruiting_mode,
        "source": "recruits_for",
        # Observed signal from the built export; null on the seed.
        "iitk_presence": m.iitk_presence,
        "presence_strength": m.presence_strength,
        "branch_affinity": m.branch_affinity,
        "factors": m.factors,
    } for m in matches]

    return {
        "available": True,
        "entries": entries,
        "track": track,
        "model_version": MODEL_VERSION,
        "disclosure": DISCLOSURE,
        "driving_pillar": driver,
        "kg_schema_version": kg.schema_version,
        "kg_is_export": kg.is_export,
        "kg_exported_at": kg.exported_at,
        "ppo_dominant_excluded": excluded,
        "campus_recruiter_pool": pool,
        "shown": len(entries),
        "branch_used": branch,
    }
