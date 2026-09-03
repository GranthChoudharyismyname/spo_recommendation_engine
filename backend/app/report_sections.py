"""
The three report sections the brief names: strengths, critical gaps, formatting fixes.

Nothing here computes a new judgement. Every section is assembled from findings and
signals the pipeline already produced, so the report cannot disagree with the score it
sits beside — a strength is a pillar that actually scored well, and a gap is a finding
the rules actually raised.

Strengths matter more than they look. Every other output in this system names a problem,
which makes an evaluation read as a list of faults even for a strong candidate. This is
the one place that reports what is working, and it is held to the same standard as the
rest: each strength quotes the evidence it rests on, and if the resume does not support
one, none is invented.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# A pillar has to clear this share of its maximum to count as a strength. Set at the
# rubric's "Very Good" boundary so the claim means what a reader assumes it means.
STRENGTH_RATIO = 0.75
MAX_STRENGTHS = 3


def _pct(value: float, total: float) -> float:
    return (value / total) if total else 0.0


def _pillar_strengths(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for p in result.get("pillars") or []:
        score, maximum = p.get("score"), p.get("max_score") or 20
        if not isinstance(score, (int, float)):
            continue
        ratio = _pct(score, maximum)
        if ratio < STRENGTH_RATIO:
            continue
        out.append({
            "title": f"{p.get('label')} is a genuine strength",
            "detail": (p.get("reasoning") or "").strip()
                      or f"Scored {score}/{maximum} against the {result.get('track', {}).get('short_label', 'target')} rubric.",
            "evidence": f"{score}/{maximum}"
                        + (f" — {p['tier']}" if p.get("tier") else ""),
            "pillar": p.get("key"),
            # Weight decides ordering: a strong pillar the track cares about is a
            # better thing to say first than a strong one it barely weighs.
            "_rank": ratio * float(p.get("weight") or 0),
        })
    return out


def _signal_strengths(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    signals = result.get("extracted_signals") or {}
    out = []

    # Scholastic record — an entrance rank or olympiad the resume states outright.
    top = None
    for item in signals.get("scholastic_signals") or []:
        if item.get("tier") in ("outstanding", "very_good") or item.get("kind") == "olympiad":
            top = item
            break
    if top is None:
        pool = signals.get("scholastic_signals") or []
        top = pool[0] if pool else None
    if top:
        out.append({
            "title": "Scholastic record carries weight",
            "detail": "Recruiters read entrance and olympiad results as an independent "
                      "check on academic ability, and this resume states one plainly.",
            "evidence": (top.get("evidence") or "").strip()[:180],
            "pillar": "Academics & CPI",
            "_rank": 0.22 if top.get("tier") in ("outstanding", "very_good") else 0.16,
        })

    # Quantified impact — the ratio, not the count.
    summary = signals.get("quantified_results_summary") or {}
    ratio = summary.get("quantified_bullet_ratio")
    if isinstance(ratio, (int, float)) and ratio >= 0.25:
        out.append({
            "title": "Work is described with measured outcomes",
            "detail": "Bullets that state a measured result are what separate a described "
                      "project from a demonstrated one.",
            "evidence": f"{summary.get('quantified_bullets', 0)} of "
                        f"{summary.get('total_bullets', 0)} bullets carry a figure "
                        f"({round(ratio * 100)}%), {summary.get('total', 0)} metrics in total",
            "pillar": "SCOPE Articulation",
            "_rank": 0.20 + min(ratio, 0.6) * 0.2,
        })

    # Recruiter-graph pedigree, when a firm resolved.
    firms = [f for f in (signals.get("kg_pedigree_firms") or []) if f]
    if firms:
        names = ", ".join(str(f.get("name") or f) for f in firms[:3])
        out.append({
            "title": "Work experience carries recruiter pedigree",
            "detail": "These employers are in the campus recruiter graph, so the "
                      "experience is recognised rather than merely described.",
            "evidence": names,
            "pillar": "Work Experience",
            "_rank": 0.30,
        })

    # A clean document is a real strength; most resumes lose points here.
    breakdown = result.get("structural_breakdown") or {}
    clean = [c for c in breakdown.get("components") or [] if c.get("points_lost", 1) == 0]
    if len(clean) >= 4:
        out.append({
            "title": "Document formatting meets the SPO template",
            "detail": "Layout is the part reviewers notice before they read a word, and "
                      "this one clears most of the guideline on its own.",
            "evidence": f"{len(clean)} of {len(breakdown.get('components') or [])} layout "
                        f"checks at full marks · structure {breakdown.get('total')}/100",
            "pillar": "Structural Layout",
            "_rank": 0.14,
        })

    return out


def top_strengths(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The three things most worth saying are going well, each with its evidence."""
    candidates = _pillar_strengths(result) + _signal_strengths(result)
    candidates.sort(key=lambda c: -c["_rank"])

    picked: List[Dict[str, Any]] = []
    seen_pillars: set = set()
    for c in candidates:
        # One per pillar, so three strengths describe three different things.
        if c["pillar"] in seen_pillars:
            continue
        seen_pillars.add(c["pillar"])
        picked.append({k: v for k, v in c.items() if not k.startswith("_")})
        if len(picked) >= MAX_STRENGTHS:
            break
    return picked


def critical_missing(
    recommendations: List[Dict[str, Any]], compliance: Optional[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    What would cost the most, and what would stop a submission.

    Two different kinds of critical: a blocking compliance rule means the resume cannot
    be submitted as it stands, which outranks any number of points. Those lead.
    """
    out: List[Dict[str, Any]] = []

    for f in (compliance or {}).get("findings") or []:
        if f.get("severity") == "BLOCKING":
            out.append({
                "title": f.get("message", "").split(".")[0],
                "detail": f.get("message", ""),
                "why": "Blocks submission under the SPO guidelines.",
                "section": f.get("section"),
                "impact_points": None,
                "source": f.get("check"),
                "blocking": True,
            })

    for r in recommendations or []:
        if r.get("severity") != "HIGH":
            continue
        out.append({
            "title": r.get("title"),
            "detail": r.get("rationale"),
            "why": r.get("action"),
            "section": r.get("section"),
            "impact_points": r.get("impact_points"),
            "source": r.get("source_rule"),
            "blocking": False,
            "evidence_refs": r.get("evidence_refs") or [],
        })

    out.sort(key=lambda i: (not i["blocking"], -(i.get("impact_points") or 0)))
    return out


def formatting_fixes(
    recommendations: List[Dict[str, Any]], compliance: Optional[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Every layout correction, each tied to the place on the page it refers to.

    Layout findings already carry the region they were measured from, so each fix can
    point at the line it is about rather than describing it.
    """
    out: List[Dict[str, Any]] = []

    for r in recommendations or []:
        if r.get("section") != "Document layout":
            continue
        out.append({
            "title": r.get("title"),
            "detail": r.get("rationale"),
            "fix": r.get("action"),
            "impact_points": r.get("impact_points"),
            "source": r.get("source_rule"),
            "evidence_refs": r.get("evidence_refs") or [],
        })

    # Compliance carries the pass/fail layout rules, which are separate from the scored
    # components and would otherwise be reported nowhere near them.
    layout_checks = ("SPO_PAGE_COUNT", "SPO_FONT_COLOUR", "SPO_FONT_FAMILY_COUNT",
                     "SPO_PREFERRED_FONT")
    for f in (compliance or {}).get("findings") or []:
        if f.get("check") in layout_checks:
            out.append({
                "title": f.get("message", "").split(".")[0],
                "detail": f.get("message", ""),
                "fix": f.get("guideline", ""),
                "impact_points": None,
                "source": f.get("check"),
                "evidence_refs": [],
            })

    out.sort(key=lambda i: -(i.get("impact_points") or 0))
    return out


def build(result: Dict[str, Any]) -> Dict[str, Any]:
    """The three named sections, assembled from what the pipeline already found."""
    recs = result.get("recommendations") or []
    compliance = result.get("compliance")
    return {
        "top_strengths": top_strengths(result),
        "critical_missing": critical_missing(recs, compliance),
        "formatting_fixes": formatting_fixes(recs, compliance),
    }
