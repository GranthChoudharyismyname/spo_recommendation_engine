"""
Canonical placement-track registry.

Single source of truth for the five tracks. `scorer_engine.ROLE_WEIGHTS` is the
authority for the weight vectors themselves; this module owns everything the
scorer does not (display copy, the project-pillar label per track, and the
mapping onto the recruiter knowledge graph's own role vocabulary).

Nothing here changes scoring mathematics.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List


@dataclass(frozen=True)
class TrackDefinition:
    code: str
    label: str
    short_label: str
    description: str
    # scorer_engine's per-track project pillar label (project_label_map in score_resume)
    project_pillar_label: str
    # The recruiter graph uses a shorter role vocabulary than scorer_engine does.
    kg_role: str


TRACKS: Dict[str, TrackDefinition] = {
    "ANALYST_AIML": TrackDefinition(
        code="ANALYST_AIML",
        label="Analytics, Data Science & Applied AI/ML",
        short_label="Analytics & AI/ML",
        description="Weights work experience and ML project depth equally; statistical and model metrics carry the SCOPE pillar.",
        project_pillar_label="Projects & ML Depth",
        kg_role="ANALYST",
    ),
    "CONSULT_PM": TrackDefinition(
        code="CONSULT_PM",
        label="Management Consulting & Product Management",
        short_label="Consulting & PM",
        description="Leadership and positions of responsibility carry the heaviest single weight, tied with work experience.",
        project_pillar_label="Projects & Strategic Initiatives",
        kg_role="CONSULT",
    ),
    "CORE_TECHNOM": TrackDefinition(
        code="CORE_TECHNOM",
        label="Core Engineering, Supply Chain & Techno-Management",
        short_label="Core & Techno-Mgmt",
        description="Branch match and ground-level PoR weigh heavily; coursework is folded into the SCOPE pillar.",
        project_pillar_label="Core Projects & Research Pedigree",
        kg_role="CORE",
    ),
    "QUANT": TrackDefinition(
        code="QUANT",
        label="Quantitative Finance & High-Frequency Trading",
        short_label="Quant & HFT",
        description="Academics and CPI dominate at 35%; mathematical and systems depth is the second pillar.",
        project_pillar_label="Projects & Technical/Math Depth",
        kg_role="QUANT",
    ),
    "SDE": TrackDefinition(
        code="SDE",
        label="Software Development Engineering & Systems",
        short_label="Software Engineering",
        description="Work experience leads, with systems depth, academics and branch match close behind.",
        project_pillar_label="Projects & Systems Depth",
        kg_role="SDE",
    ),
}

TRACK_CODES: List[str] = list(TRACKS.keys())


def get_track(code: str) -> TrackDefinition:
    try:
        return TRACKS[code]
    except KeyError:
        raise ValueError(
            f"Invalid track '{code}'. Must be one of: {TRACK_CODES}"
        ) from None


def track_payload(code: str) -> dict:
    return asdict(get_track(code))
