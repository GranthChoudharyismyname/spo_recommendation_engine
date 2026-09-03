"""
Adapter over the curated IITK recruiter knowledge graph (`companies.seed.json`).

Two facts from the KG's own schema drive everything here and must not be collapsed:

  recruits_for   this firm hires for this role at IITK; drives the campus panel.
  pedigree_for   an internship here is a positive signal when scoring past work
                 experience, and is never surfaced as somewhere you could get an offer.

  recruiting_mode == PPO_DOMINANT means the firm hires almost entirely intern-to-PPO.
                 A near-empty campus panel for those firms is correct behaviour, so
                 they are excluded from the shortlist-fit panel by construction.

The KG uses a shorter role vocabulary (SDE/QUANT/ANALYST/CONSULT/CORE) than the scorer
(SDE/QUANT/ANALYST_AIML/CONSULT_PM/CORE_TECHNOM). The mapping lives once, in tracks.py.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import KG_EXPORT_PATH, KG_SEED_PATH
from tracks import get_track

PPO_DOMINANT = "PPO_DOMINANT"

TIER_LABEL_FALLBACK = {"1": "Outstanding / Tier-1", "2": "Very Good",
                       "3": "Good", "4": "Neutral"}

# The export names the current placement cycle as a key under `observed`.
def _latest_cycle(observed: Dict[str, Any]) -> Optional[str]:
    return max(observed) if observed else None


# The KG's tier_scale, restated as the vocabulary scorer_engine's rubrics use. The
# rubrics band Tier-1 at 18-20 points, Tier-2 at 14-17 and Tier-3 at 10-13, so carrying
# the word alongside the integer lets the qualitative evaluator bind one to the other
# instead of inferring what "tier": 2 is supposed to mean.
TIER_LABEL = {1: "Outstanding / Tier-1", 2: "Very Good / Tier-2",
              3: "Good / Tier-3", 4: "Neutral / Tier-4"}
TIER_RUBRIC_BAND = {1: "18-20", 2: "14-17", 3: "10-13", 4: "0-9"}


@dataclass(frozen=True)
class RecruiterMatch:
    """One recruiter ranked for a specific candidate, with the evidence behind it."""
    company_id: str
    display_name: str
    category: str
    tier: int
    tier_label: str
    recruiting_mode: str
    iitk_presence: str
    # Observed at IITK this cycle for this role, 0-1. None when never observed.
    presence_strength: Optional[float]
    evidence_strength: Optional[float]
    # Share of this firm's IITK hiring that came from the candidate's branch, and how
    # much observation stands behind that share. History, never a criterion.
    branch_affinity: Optional[float]
    branch_evidence: Optional[float]
    fit: int
    band: str
    rationale: str
    factors: Dict[str, Any]


@dataclass(frozen=True)
class CompanyTierInfo:
    company_id: str
    display_name: str
    category: str
    tier: int
    edge_type: str          # "recruits_for" | "pedigree_for"
    recruiting_mode: str
    source: str

    @property
    def tier_label(self) -> str:
        return TIER_LABEL.get(self.tier, f"Tier-{self.tier}")

    @property
    def rubric_band(self) -> str:
        return TIER_RUBRIC_BAND.get(self.tier, "0-9")


def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


class KnowledgeGraph:
    def __init__(self, payload: Dict[str, Any], path: Path):
        self.path = path
        self.schema_version = payload.get("schema_version") or payload.get("kb_version")
        self.tier_scale: Dict[str, str] = payload.get("tier_scale", TIER_LABEL_FALLBACK)
        self.companies: List[Dict[str, Any]] = payload.get("companies", [])
        # Present only in a built export: role-level branch rollups and the cycle stamp.
        self.role_branch_signals: Dict[str, Any] = payload.get("role_branch_signals") or {}
        self.exported_at: Optional[str] = payload.get("exported_at")
        # A built export carries observed IITK recruiting; the seed does not.
        self.is_export: bool = any("observed" in c or "iitk_presence" in c
                                   for c in self.companies)
        self._by_alias: Dict[str, Dict[str, Any]] = {}
        for company in self.companies:
            names = [company.get("display_name", "")] + list(company.get("aliases") or [])
            for name in names:
                key = _normalise(name)
                if key:
                    self._by_alias.setdefault(key, company)

    # ---------------------------------------------------------------- lookup

    def resolve(self, name: str, *, fuzzy_cutoff: float = 0.88) -> Optional[Dict[str, Any]]:
        key = _normalise(name)
        if not key:
            return None
        if key in self._by_alias:
            return self._by_alias[key]
        # Resume strings carry suffixes ("Google India", "Texas Instruments Pvt Ltd").
        for alias_key, company in self._by_alias.items():
            if len(alias_key) >= 4 and (
                key.startswith(alias_key + " ") or f" {alias_key} " in f" {key} "
            ):
                return company
        best, best_ratio = None, 0.0
        for alias_key, company in self._by_alias.items():
            ratio = SequenceMatcher(None, key, alias_key).ratio()
            if ratio > best_ratio:
                best, best_ratio = company, ratio
        return best if best_ratio >= fuzzy_cutoff else None

    def _tier_info(self, name: str, track: str, edge_type: str) -> Optional[CompanyTierInfo]:
        company = self.resolve(name)
        if not company:
            return None
        role = get_track(track).kg_role
        edge = (company.get(edge_type) or {}).get(role)
        if not edge:
            return None
        return CompanyTierInfo(
            company_id=company["id"],
            display_name=company["display_name"],
            category=company.get("category", ""),
            tier=int(edge.get("tier", 4)),
            edge_type=edge_type,
            recruiting_mode=company.get("recruiting_mode", ""),
            source=edge.get("source", ""),
        )

    def get_company_tier(self, name: str, track: str) -> Optional[CompanyTierInfo]:
        return self._tier_info(name, track, "recruits_for")

    def get_pedigree_tier(self, name: str, track: str) -> Optional[CompanyTierInfo]:
        return self._tier_info(name, track, "pedigree_for") or self._tier_info(
            name, track, "recruits_for"
        )

    def is_known(self, name: str) -> bool:
        return self.resolve(name) is not None

    def campus_recruiters(self, track: str) -> List[CompanyTierInfo]:
        """Firms with a real campus channel for this track. PPO_DOMINANT firms excluded."""
        role = get_track(track).kg_role
        out: List[CompanyTierInfo] = []
        for company in self.companies:
            edge = (company.get("recruits_for") or {}).get(role)
            if not edge:
                continue
            if company.get("recruiting_mode") == PPO_DOMINANT:
                continue
            # The export carries firms whose tier was never curated; the builder leaves
            # them null rather than guessing, so they sort last instead of being dropped.
            tier = edge.get("tier")
            out.append(
                CompanyTierInfo(
                    company_id=company["id"],
                    display_name=company["display_name"],
                    category=company.get("category") or "",
                    tier=int(tier) if isinstance(tier, (int, float)) else 4,
                    edge_type="recruits_for",
                    recruiting_mode=company.get("recruiting_mode") or "",
                    source=edge.get("source") or "",
                )
            )
        out.sort(key=lambda c: (c.tier, c.display_name))
        return out

    # ------------------------------------------------------------------ matching

    def _observation(self, company: Dict[str, Any], role: str) -> Dict[str, Any]:
        """This cycle's observed recruiting for one firm and role. Empty on the seed."""
        observed = company.get("observed") or {}
        cycle = _latest_cycle(observed)
        if not cycle:
            return {}
        return (observed.get(cycle) or {}).get(role) or {}

    def _branch_affinity(self, company: Dict[str, Any], branch: str) -> Optional[float]:
        """
        Share of this firm's observed IITK hiring that came from `branch`.

        Evidence, never a gate. The knowledge graph's own README is explicit: render it
        as history, never as a criterion. It nudges ordering and is quoted as what the
        firm did last cycle; it never excludes a candidate.
        """
        if not branch:
            return None
        for entry in company.get("branch_affinity") or []:
            if entry.get("resolved") and entry.get("branch") == branch:
                value = entry.get("affinity")
                return float(value) if isinstance(value, (int, float)) else None
        return None

    def match_recruiters(
        self,
        *,
        track: str,
        overall_score: float,
        branch: Optional[str] = None,
        tier_bars: Optional[Dict[int, float]] = None,
        limit: Optional[int] = None,
    ) -> List[RecruiterMatch]:
        """
        Recruiters ranked for one candidate.

        Ranking previously used the tier bar alone, so every Tier-1 firm scored
        identically and the list was effectively arbitrary. Three observed signals now
        separate them, all from the built export:

          presence_strength   how much this firm actually recruited at IITK for this role
                              in the latest cycle
          branch_affinity     the share of its IITK hiring that came from this branch
          evidence_strength   the graph's own shrinkage, so a thin observation moves the
                              ranking less than a well-evidenced one

        The tier bar still sets the base, so the reading remains "how does this profile
        compare with what this tier expects".
        """
        role = get_track(track).kg_role
        bars = tier_bars or {1: 80.0, 2: 70.0, 3: 58.0, 4: 58.0}
        matches: List[RecruiterMatch] = []

        for company in self.companies:
            edge = (company.get("recruits_for") or {}).get(role)
            if not edge:
                continue
            mode = company.get("recruiting_mode") or ""
            presence = company.get("iitk_presence") or ""
            # No campus channel: excluded by construction, as the graph intends.
            if mode == PPO_DOMINANT or presence == "ppo_only_expected":
                continue

            raw_tier = edge.get("tier")
            # The builder leaves a tier null rather than guessing. Such a firm must not
            # inherit Tier-4's easy bar, or every uncurated startup outranks Google
            # purely by being easier to clear.
            tier_known = isinstance(raw_tier, (int, float))
            tier = int(raw_tier) if tier_known else 0
            obs = self._observation(company, role)
            presence_strength = obs.get("presence_strength")
            evidence_strength = obs.get("evidence_strength")
            affinity = self._branch_affinity(company, branch or "")
            branch_evidence = company.get("branch_evidence_strength")

            bar = bars.get(tier, UNCURATED_BAR)
            base = _logistic(overall_score - bar)
            factors: Dict[str, Any] = {"tier_base": round(base, 4)}
            score = base

            # Actively recruiting here counts for more than a curated tier alone.
            if isinstance(presence_strength, (int, float)):
                weight = float(evidence_strength) if isinstance(evidence_strength, (int, float)) else 0.5
                bump = 0.18 * float(presence_strength) * weight
                score += bump
                factors["observed_presence"] = round(bump, 4)
            elif self.is_export and presence == "not_observed_at_iitk":
                # Curated as a recruiter but not seen in the latest cycle. Ranked lower,
                # not removed: a firm can be new or simply absent for a year.
                score -= 0.12
                factors["not_observed"] = -0.12

            if isinstance(affinity, (int, float)):
                weight = float(branch_evidence) if isinstance(branch_evidence, (int, float)) else 0.5
                bump = 0.22 * float(affinity) * weight
                score += bump
                factors["branch_history"] = round(bump, 4)

            fit = int(round(max(3.0, min(97.0, score * 100))))
            matches.append(
                RecruiterMatch(
                    company_id=company["id"],
                    display_name=company["display_name"],
                    category=company.get("category") or "",
                    tier=tier,
                    tier_label=(self.tier_scale.get(str(tier), f"Tier-{tier}")
                                if tier_known else "Tier not curated"),
                    recruiting_mode=mode,
                    iitk_presence=presence,
                    presence_strength=presence_strength,
                    evidence_strength=evidence_strength,
                    branch_affinity=affinity,
                    branch_evidence=branch_evidence,
                    fit=fit,
                    band=_band(fit),
                    rationale=_rationale(
                        tier if tier_known else None, bar, overall_score,
                        presence_strength, affinity, branch, presence,
                    ),
                    factors=factors,
                )
            )

        # Tier first, because the panel answers "which recruiters are worth targeting",
        # and a Tier-1 firm you are near is a better answer than an uncurated one you
        # clear comfortably. Fit, observed presence and branch history order within tier.
        # Uncurated tiers (0) sort last rather than first.
        matches.sort(key=lambda m: (
            m.tier if m.tier else 99,
            -m.fit,
            -(m.presence_strength or 0.0),
            m.display_name,
        ))
        return matches[:limit] if limit else matches


# Bar used when the graph has no curated tier for a firm. Deliberately not Tier-4's,
# which would make an uncurated firm look like the easiest and therefore best fit.
UNCURATED_BAR = 70.0


def _logistic(delta: float, slope: float = 6.0) -> float:
    import math
    return 1.0 / (1.0 + math.exp(-delta / slope))


def _band(fit: int) -> str:
    if fit >= 65:
        return "Strong"
    if fit >= 40:
        return "Competitive"
    return "Stretch"


def _rationale(
    tier: Optional[int], bar: float, score: float,
    presence: Optional[float], affinity: Optional[float],
    branch: Optional[str], iitk_presence: str,
) -> str:
    """Plain sentences. Branch is phrased as the firm's history, never as eligibility."""
    delta = score - bar
    label = f"Tier-{tier}" if tier else "uncurated"
    if delta >= 6:
        parts = [f"Profile sits {delta:.0f} points above the {label} bar of {bar:.0f}."]
    elif delta >= -6:
        parts = [f"Profile sits near the {label} bar of {bar:.0f}."]
    else:
        parts = [f"Profile sits {abs(delta):.0f} points below the {label} bar of {bar:.0f}."]

    if isinstance(presence, (int, float)) and presence > 0:
        parts.append("Actively recruited at IIT Kanpur for this role last cycle.")
    elif iitk_presence == "not_observed_at_iitk":
        parts.append("Not observed recruiting at IIT Kanpur in the latest cycle.")

    if isinstance(affinity, (int, float)) and affinity >= 0.1 and branch:
        parts.append(
            f"{affinity:.0%} of its IIT Kanpur hiring last cycle came from {branch}."
        )
    return " ".join(parts)


@lru_cache(maxsize=1)
def load_kg() -> Optional[KnowledgeGraph]:
    """
    Loaded once per process and cached.

    The built export wins when present — it has 207 companies with observed IITK
    recruiting and branch affinity, against the seed's 78 with tiers alone.
    """
    for path in (Path(KG_EXPORT_PATH), Path(KG_SEED_PATH)):
        if not path.exists():
            continue
        try:
            with path.open() as fp:
                return KnowledgeGraph(json.load(fp), path)
        except (json.JSONDecodeError, KeyError, OSError):
            continue
    return None
