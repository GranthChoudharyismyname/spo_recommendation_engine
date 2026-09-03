"""
Phase 3 — Agentic recommendation engine.

Runs on every evaluation. Validation findings are context the advice must not contradict,
never a gate — withholding advice from a candidate whose report raised a finding leaves
them with nothing actionable. Genuinely multi-step, not one free-associating call:

  1. ATTRIBUTE   rank pillars by (track weight x headroom), so advice targets the
                 highest-LEVERAGE fix rather than merely the lowest score, and compute
                 the distance to the next verdict threshold.
  2. GROUND      build candidate recommendations from evidence already computed —
                 specific bullets, specific signals, specific validation findings.
                 The deterministic rules in recommendations.py supply the spine; the
                 model rewrites them against the candidate's actual text and may add
                 items, but only ones citing a real field.
  3. CRITIQUE    a second, explicit pass rejects any recommendation that contradicts a
                 validation finding, asks the candidate to fabricate a number, treats
                 branch or PoR detection as an eligibility gate, or is generic filler.
                 Rejections are recorded, not silently dropped.

Hard rules enforced in code as well as in the prompt, because a prompt is not a
guarantee:
  * Never ask a candidate to invent or estimate a metric.
  * Never suggest applying to a PPO_DOMINANT firm as a campus action.
  * Never surface `candidate_source` or any verbatim `evidence` from the signal corpora.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from llm import LLMError, generate_json
from tracks import get_track

logger = logging.getLogger("resume_intelligence.recommendation")

AGENT_VERSION = "recommendation-agent-v1"

# scorer_engine's own verdict thresholds.
VERDICT_THRESHOLDS: List[Tuple[int, str]] = [
    (90, "Top 1% Day-1 Prime"),
    (80, "Outstanding (Strong Shortlist Contender)"),
    (70, "Very Good (Shortlist Contender)"),
    (58, "Good / Borderline"),
]

# Phrases that ask a candidate to manufacture evidence. Checked after generation.
_FABRICATION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        # "add a 30% improvement", "include an impressive metric". No trailing \b after a
        # literal % — % is a non-word character, so \b there can never match.
        r"\b(?:add|include|insert|put in|throw in|append)\s+(?:a|an|some|any)?\s*"
        r"(?:\d+\s*%|\d+\s*x\b|impressive|strong|compelling|big|rough|ballpark|placeholder)",
        r"\b(?:make up|made up|invent|fabricate|manufacture)\b",
        r"\b(?:estimate|approximate|guess|assume)\s+(?:a|an|the|some)?\s*"
        r"(?:number|metric|figure|percentage|value|impact|improvement|result)",
        r"\bclaim\s+(?:a|an|that you)\b",
        r"\beven if you (?:did ?n[o']?t|didnt|never) (?:measure|track|record|compute)",
        r"\bsomething like\s+\d",
        r"\binflate\b|\bexaggerate\b|\bembellish\b",
        r"\bround (?:it |them )?up\b",
        r"\bif you don'?t have (?:a |the )?(?:number|metric|figure)[^.]{0,30}(?:just|simply|still)",
    ]
]

# Advice that treats a fixed attribute as an eligibility gate.
_GATE_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\byou (?:are|aren'?t|are not) eligible\b",
        r"\b(?:switch|change|transfer) (?:your )?(?:branch|department|major)\b",
        r"\bnot (?:a )?(?:fit|suitable) for this (?:track|role) because of your branch\b",
        r"\bconsider a different (?:track|branch)\b",
    ]
]


# ---------------------------------------------------------------- step 1: attribution

def _weight_for(pillar: str, weights: Dict[str, float]) -> float:
    if pillar in weights:
        return weights[pillar]
    if pillar.startswith("Projects") or pillar.startswith("Core Projects"):
        return weights.get("Projects & Depth", 0.0)
    return 0.0


def attribute_gap(
    result: Dict[str, Any], track: str, weights: Dict[str, float]
) -> Dict[str, Any]:
    """Where the points actually are, and how far the next verdict band is."""
    overall = float(result.get("overall_score") or 0)

    next_band = None
    for threshold, label in sorted(VERDICT_THRESHOLDS):
        if overall < threshold:
            next_band = {"threshold": threshold, "label": label,
                         "points_needed": round(threshold - overall, 1)}
            break

    ranked = []
    for name, entry in (result.get("pillars") or {}).items():
        if not isinstance(entry, dict):
            continue
        score = entry.get("score")
        if not isinstance(score, (int, float)):
            continue
        weight = _weight_for(name, weights)
        # Points this pillar could still add to the composite: weight x headroom x 5 x 0.85.
        leverage = round(weight * (20 - score) * 5 * 0.85, 2)
        ranked.append({
            "pillar": name, "score": score, "weight": round(weight, 4),
            "headroom_points": leverage, "tier": entry.get("tier"),
            "reasoning": entry.get("reasoning"),
        })
    ranked.sort(key=lambda p: -p["headroom_points"])

    structural = float(result.get("structural_score") or 0)
    layout_headroom = round((100 - structural) * 0.15, 2)

    return {
        "overall_score": overall,
        "next_band": next_band,
        "ranked_pillars": ranked,
        "layout_headroom_points": layout_headroom,
        "total_available": round(sum(p["headroom_points"] for p in ranked) + layout_headroom, 1),
    }


# ---------------------------------------------------------------- step 2: grounding

_SPIKE_PATTERN_HINTS = {
    "SDE": "candidates scoring Outstanding here typically state a throughput or latency delta "
           "against a named baseline, not the tool stack they used",
    "QUANT": "candidates scoring Outstanding here typically state a measured performance figure "
             "— Sharpe, drawdown, nanosecond latency, convergence order — not the library used",
    "ANALYST_AIML": "candidates scoring Outstanding here typically pair the model metric with "
                    "the baseline it beat and the dataset size, not the metric alone",
    "CONSULT_PM": "candidates scoring Outstanding here typically state the decision gate the work "
                  "cleared and the business figure it moved, not the analysis performed",
    "CORE_TECHNOM": "candidates scoring Outstanding here typically state the physical or "
                    "operational quantity improved and the scale of the crew or plant involved",
}


def _blocked_companies(kg: Any, track: str) -> List[str]:
    """PPO_DOMINANT firms — no campus channel, so never a concrete campus action."""
    if kg is None:
        return []
    role = get_track(track).kg_role
    return [
        c.get("display_name", "")
        for c in kg.companies
        if (c.get("recruits_for") or {}).get(role) and c.get("recruiting_mode") == "PPO_DOMINANT"
    ]


_GENERATION_SYSTEM = """You are an IIT Kanpur placement reviewer writing recommendations for one
candidate's resume. You are given the scoring breakdown, the candidate's actual extracted resume,
the gap attribution, findings from a validation pass, and a set of deterministic rule findings.

Your job is to turn those into specific, evidence-grounded recommendations.

ABSOLUTE RULES — a recommendation breaking any of these will be rejected:
1. NEVER ask the candidate to invent, estimate, approximate or inflate a number. You may ask
   them to STATE a metric they already measured, or to describe what shipped if nothing was
   measured. "Add a 30% improvement" is forbidden. "Add the evaluation number you recorded"
   is correct.
2. NEVER treat branch, department or PoR-tier detection as an eligibility gate. Branch is
   fixed. If branch match is low, reframe as which pillars carry more relative weight for
   this candidate.
3. A position of responsibility outside the Gymkhana tier list is a real role the list does
   not cover, never an invalid or unrecognised one. Do NOT tell the candidate to seek
   leadership roles, and do NOT tell them to rename or re-title the position. Comment on what
   the role involved instead: the number of people led and across how many teams, the budget
   and vendors handled, the turnout managed and whether it ran without incident.
4. Every recommendation MUST cite something specific from THIS resume — a bullet, an
   organisation, a field. If you cannot point at the exact text, do not write the item.
5. NEVER name a company from the blocked list as somewhere to apply. Those firms hire almost
   entirely through intern-to-PPO; a campus application channel does not exist for them.
6. Write in plain, direct language. No motivational filler, no "AI suggests", no praise
   padding. Say what is weak, why it costs points, and what to change.

Prefer rewriting the supplied deterministic findings into sharper, resume-specific language
over inventing new items. You may add at most two new items, and only if they cite real text."""


def generate_recommendations(
    *,
    result: Dict[str, Any],
    track: str,
    attribution: Dict[str, Any],
    validation: Dict[str, Any],
    rule_findings: List[Dict[str, Any]],
    blocked_companies: List[str],
    api_key: Optional[str],
) -> List[Dict[str, Any]]:
    resume = result.get("structured_resume") or {}
    track_def = get_track(track)

    prompt = (
        f"TARGET TRACK: {track} — {track_def.label}\n\n"
        f"GAP ATTRIBUTION (pillars ranked by weight x headroom):\n{json.dumps(attribution, indent=2)}\n\n"
        f"VALIDATION FINDINGS (must not be contradicted):\n"
        f"{json.dumps(validation.get('findings', []), indent=2)[:6000]}\n\n"
        f"DETERMINISTIC RULE FINDINGS (your spine — sharpen these):\n"
        f"{json.dumps(rule_findings, indent=2)[:9000]}\n\n"
        f"CANDIDATE'S EXTRACTED RESUME:\n{json.dumps(resume, indent=2)[:14000]}\n\n"
        f"WHAT OUTSTANDING LOOKS LIKE ON THIS TRACK (pattern, not a quote): "
        f"{_SPIKE_PATTERN_HINTS.get(track, '')}\n\n"
        f"BLOCKED COMPANIES (never name as a campus application target): "
        f"{json.dumps(blocked_companies)}\n\n"
        "Return JSON:\n"
        '{"recommendations": [{\n'
        '  "id": "<stable kebab id>",\n'
        '  "severity": "HIGH" | "IMPORTANT" | "POLISH",\n'
        '  "pillar": "<exact pillar name from the attribution>",\n'
        '  "section": "<resume section this concerns>",\n'
        '  "issue": "<one sentence: what is weak>",\n'
        '  "evidence_ref": "<the VERBATIM resume text this is about, copied exactly, or the '
        'exact signal field name such as cpi_status>",\n'
        '  "suggested_action": "<what to change, concretely>",\n'
        '  "expected_impact": "<which pillar this moves and roughly how much>",\n'
        '  "source_rule": "<the deterministic rule id you sharpened, or AGENT_DERIVED>"\n'
        "}]}"
    )

    data = generate_json(prompt=prompt, system_instruction=_GENERATION_SYSTEM,
                         api_key=api_key, stage="recommendation-generation", temperature=0.3)
    items = data.get("recommendations")
    return items if isinstance(items, list) else []


# ---------------------------------------------------------------- step 3: self-critique

_CRITIQUE_SYSTEM = """You are auditing draft resume recommendations before they are shown to a
candidate. For each one, decide KEEP or REJECT.

REJECT if the recommendation:
  A. Asks the candidate to invent, estimate, approximate or inflate any number or outcome.
  B. Contradicts one of the validation findings supplied.
  C. Treats branch, department or PoR-tier detection as an eligibility gate rather than as
     descriptive context.
  D. Tells a candidate holding a position outside the Gymkhana tier list to "seek leadership
     roles", to rename the position, or describes that position as unrecognised or unlisted.
     The role was held; only the institute's tier list does not cover it.
  E. Is generic filler that could apply to any resume — if the evidence_ref does not quote or
     name something specific from this candidate, reject it.
  F. Names a blocked (PPO-dominant) company as somewhere to apply.

KEEP otherwise. Be strict on A and E; those are the two that make advice useless or harmful.
Return a verdict for EVERY id you were given."""


def critique(
    *,
    drafts: List[Dict[str, Any]],
    validation: Dict[str, Any],
    blocked_companies: List[str],
    resume: Dict[str, Any],
    api_key: Optional[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Returns (kept, rejected). Rejections carry the reason, and are reported, not hidden."""
    kept: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    # --- deterministic gate first. A prompt is not a guarantee, so the hard rules are
    # enforced in code before the model is consulted at all.
    survivors: List[Dict[str, Any]] = []
    blocked_lower = [b.lower() for b in blocked_companies if b]

    for item in drafts:
        text = " ".join(str(item.get(k) or "") for k in
                        ("issue", "suggested_action", "expected_impact"))
        low = text.lower()

        hit = next((p.pattern for p in _FABRICATION_PATTERNS if p.search(text)), None)
        if hit:
            rejected.append({**item, "rejected_by": "code",
                             "rejection_reason": "Asks the candidate to fabricate or estimate a "
                                                 "figure, which is a hard rule violation."})
            continue

        hit = next((p.pattern for p in _GATE_PATTERNS if p.search(text)), None)
        if hit:
            rejected.append({**item, "rejected_by": "code",
                             "rejection_reason": "Treats a fixed attribute as an eligibility "
                                                 "gate rather than as weighting context."})
            continue

        named = next((b for b in blocked_lower if b and b in low), None)
        if named:
            rejected.append({**item, "rejected_by": "code",
                             "rejection_reason": f"Names '{named}', which hires almost entirely "
                                                 "through intern-to-PPO; no campus channel exists."})
            continue

        # Evidence must actually appear in the resume, or name a real signal field.
        ref = str(item.get("evidence_ref") or "").strip()
        if not ref:
            rejected.append({**item, "rejected_by": "code",
                             "rejection_reason": "No evidence reference, so the item cannot be "
                                                 "tied to anything in this resume."})
            continue

        survivors.append(item)

    if not survivors:
        return kept, rejected

    # --- model critique for the judgement calls code cannot make (generic filler,
    # contradicting a validation finding).
    try:
        data = generate_json(
            prompt=(
                f"VALIDATION FINDINGS:\n{json.dumps(validation.get('findings', []), indent=2)[:6000]}\n\n"
                f"BLOCKED COMPANIES:\n{json.dumps(blocked_companies)}\n\n"
                f"DRAFT RECOMMENDATIONS:\n{json.dumps(survivors, indent=2)[:14000]}\n\n"
                'Return JSON: {"verdicts": [{"id": "<id>", "verdict": "KEEP" | "REJECT", '
                '"reason": "<why, one sentence>"}]}'
            ),
            system_instruction=_CRITIQUE_SYSTEM,
            api_key=api_key, stage="recommendation-critique", temperature=0.0,
        )
        verdicts = {
            str(v.get("id")): v for v in (data.get("verdicts") or []) if v.get("id")
        }
    except LLMError as exc:
        logger.warning("critique pass unavailable: %s", exc)
        # The deterministic gate already ran; keep survivors but mark the pass as skipped.
        for item in survivors:
            kept.append({**item, "critique": "not_run"})
        return kept, rejected

    for item in survivors:
        verdict = verdicts.get(str(item.get("id")))
        if verdict and str(verdict.get("verdict") or "").upper() == "REJECT":
            rejected.append({**item, "rejected_by": "critique",
                             "rejection_reason": str(verdict.get("reason") or "").strip()
                                                 or "Rejected by the self-critique pass."})
        else:
            kept.append({**item, "critique": "kept"})
    return kept, rejected


# ---------------------------------------------------------------- markdown summary

def to_markdown(
    *, result: Dict[str, Any], track: str, attribution: Dict[str, Any],
    recommendations: List[Dict[str, Any]],
) -> str:
    track_def = get_track(track)
    lines: List[str] = []
    lines.append(f"# Resume review — {track_def.label}")
    lines.append("")
    lines.append(f"**Score {result.get('overall_score')}/100** · {result.get('verdict')}")
    nb = attribution.get("next_band")
    if nb:
        lines.append("")
        lines.append(f"You are **{nb['points_needed']} points** below *{nb['label']}* "
                     f"(threshold {nb['threshold']}).")
    lines.append("")
    lines.append("## Where the points are")
    lines.append("")
    lines.append("| Pillar | Score | Weight | Points still available |")
    lines.append("| --- | ---: | ---: | ---: |")
    for p in attribution.get("ranked_pillars", []):
        lines.append(f"| {p['pillar']} | {p['score']}/20 | {p['weight']*100:.0f}% | "
                     f"{p['headroom_points']:.1f} |")
    if attribution.get("layout_headroom_points"):
        lines.append(f"| Document layout | {result.get('structural_score')}/100 | 15% | "
                     f"{attribution['layout_headroom_points']:.1f} |")
    lines.append("")

    order = {"HIGH": 0, "IMPORTANT": 1, "POLISH": 2}
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for r in sorted(recommendations, key=lambda x: order.get(x.get("severity", "POLISH"), 3)):
        grouped.setdefault(r.get("severity", "POLISH"), []).append(r)

    titles = {"HIGH": "High priority", "IMPORTANT": "Important", "POLISH": "Polish"}
    for severity in ("HIGH", "IMPORTANT", "POLISH"):
        items = grouped.get(severity)
        if not items:
            continue
        lines.append(f"## {titles[severity]}")
        lines.append("")
        for r in items:
            lines.append(f"**{r.get('issue')}**")
            lines.append("")
            ref = str(r.get("evidence_ref") or "").strip()
            if ref:
                lines.append(f"> {ref}")
                lines.append("")
            lines.append(f"{r.get('suggested_action')}")
            lines.append("")
            meta = " · ".join(x for x in [
                r.get("section"), r.get("pillar"), r.get("expected_impact")] if x)
            if meta:
                lines.append(f"<sub>{meta}</sub>")
                lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*Recommendations are grounded in your extracted resume and this engine's "
                 "scoring breakdown. None of them asks you to add a figure you did not measure.*")
    return "\n".join(lines)


# ---------------------------------------------------------------- orchestration

def recommend(
    *,
    result: Dict[str, Any],
    track: str,
    weights: Dict[str, float],
    validation: Dict[str, Any],
    rule_findings: List[Dict[str, Any]],
    kg: Any = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Full three-step pipeline. Raises LLMError if the model is unreachable."""
    # Validation findings are passed into the generation and critique prompts as context
    # the advice must not contradict — they are not a gate. A student whose evaluation
    # raised a critical finding needs the advice more, not less; the finding is shown
    # beside it so they can weigh both.

    attribution = attribute_gap(result, track, weights)
    blocked = _blocked_companies(kg, track)

    # Trim the rule findings the agent sees to the fields it needs, so corpus internals
    # and candidate_source values can never reach the prompt.
    spine = [
        {k: v for k, v in r.items()
         if k in ("id", "severity", "title", "rationale", "action", "section",
                  "pillar", "evidence_text", "source_rule", "expected_impact")}
        for r in rule_findings
    ]

    drafts = generate_recommendations(
        result=result, track=track, attribution=attribution, validation=validation,
        rule_findings=spine, blocked_companies=blocked, api_key=api_key,
    )
    kept, rejected = critique(
        drafts=drafts, validation=validation, blocked_companies=blocked,
        resume=result.get("structured_resume") or {}, api_key=api_key,
    )

    return {
        "agent_version": AGENT_VERSION,
        "attribution": attribution,
        "recommendations": kept,
        "rejected": rejected,
        "counts": {
            "drafted": len(drafts),
            "kept": len(kept),
            "rejected": len(rejected),
            "rejected_by_code": sum(1 for r in rejected if r.get("rejected_by") == "code"),
            "rejected_by_critique": sum(1 for r in rejected if r.get("rejected_by") == "critique"),
        },
        "blocked_companies_considered": blocked,
        "markdown": to_markdown(result=result, track=track, attribution=attribution,
                                recommendations=kept),
    }
