"""
Phase 2 — Agentic validation engine.

Runs after `score_resume()` and before any result reaches a human. It is a small agent
loop of independently named checks, not one regex pass: each check is a function
returning zero or more structured findings, they are registered in a list, and adding a
future check means appending to that list rather than editing a monolith.

Two of the checks call the LLM (grounding of extracted fields, and grounding of the
qualitative reasoning). The rest are deterministic. Every check is wrapped so that one
failing check degrades to a WARNING finding instead of taking down the whole report.

Status semantics:
  PASS                every check clean
  PASS_WITH_WARNINGS  something is worth a human's attention
  NEEDS_REVIEW        something serious was found — a claim that could not be traced to
                      the PDF, or an internal inconsistency

No status withholds a result. An earlier version refused to show the score on a critical
finding; in practice that fired on the evaluator's own prose being marginally broader
than the resume text, and a student lost their entire review over a wording judgement.
Findings are reported prominently against the pillar they affect, and the score is always
shown alongside them.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, List, Optional

from llm import LLMError, generate_json
from tracks import get_track

logger = logging.getLogger("resume_intelligence.validation")

# Severities describe how serious a finding is. None of them withholds a result:
# a resume review that refuses to show a score because one sentence of the evaluator's
# prose overreached is worse than useless to the student it is for. Findings are always
# surfaced; the score is always shown.
CRITICAL = "CRITICAL"
WARNING = "WARNING"
INFO = "INFO"

# Retained so existing payloads and callers keep working.
BLOCKING = CRITICAL

STATUS_PASS = "PASS"
STATUS_WARN = "PASS_WITH_WARNINGS"
STATUS_REVIEW = "NEEDS_REVIEW"
# Retained for compatibility with anything still reading the old name.
STATUS_BLOCKED = STATUS_REVIEW


@dataclass
class Finding:
    check: str
    severity: str
    message: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    affected_pillar: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationContext:
    """Everything a check may read. Checks never mutate it."""
    result: Dict[str, Any]
    track: str
    raw_markdown: str
    api_key: Optional[str]
    role_weights: Dict[str, Dict[str, float]]
    kg: Any = None
    use_llm: bool = True


# ---------------------------------------------------------------- helpers

# Typographic variants a PDF and an extractor routinely disagree on. Without folding
# these, "13.9x" and "13.9\u00d7" are different tokens and a true claim reads as fabricated.
_TYPOGRAPHIC = str.maketrans({
    "\u00d7": "x",   # multiplication sign
    "\u2212": "-", "\u2013": "-", "\u2014": "-",   # minus, en dash, em dash
    "\u2018": "'", "\u2019": "'",                   # curly single quotes
    "\u201c": '"', "\u201d": '"',                   # curly double quotes
    "\u2192": ">", "\u00a0": " ",                   # arrow, non-breaking space
    "\u2026": " ",                                  # ellipsis
})


def _normalise(text: str) -> str:
    folded = (text or "").translate(_TYPOGRAPHIC)
    return re.sub(r"\s+", " ", folded).strip().lower()


_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "over", "using", "used",
    "was", "were", "are", "his", "her", "its", "our", "their", "not", "but", "all", "any",
    "via", "per", "own", "out", "off", "than", "then", "also", "such", "each", "which",
}


def _significant_tokens(text: str) -> List[str]:
    """Words and numbers distinctive enough that their absence means the fact is absent."""
    tokens = re.findall(r"[a-z0-9][a-z0-9.+#/-]*", _normalise(text))
    return [t for t in tokens if len(t) >= 3 and t not in _STOPWORDS]


def _fuzzy_contains(needle: str, haystack: str, cutoff: float = 0.7) -> bool:
    """
    Whether the FACTS in `needle` appear in `haystack`.

    Whole-string similarity is the wrong measure: the extractor reorders and re-punctuates
    ("Adobe, India | Research Intern | May'25" for "Research Intern at Adobe, India"), so a
    windowed ratio scores a true match far too low. Token coverage is order-independent, which is what
    grounding actually requires — every distinctive token must appear somewhere in the source.
    """
    tokens = _significant_tokens(needle)
    if not tokens:
        return True
    hay = _normalise(haystack)
    hay_tokens = set(_significant_tokens(haystack))

    def present(token: str) -> bool:
        if token in hay_tokens or token in hay:
            return True
        # Tolerate a single OCR/ligature slip inside a long word.
        return len(token) >= 6 and any(
            SequenceMatcher(None, token, cand).ratio() >= 0.88
            for cand in hay_tokens
            if abs(len(cand) - len(token)) <= 2
        )

    def numeric_present(token: str) -> bool:
        if present(token):
            return True
        # Parsers disagree on spacing around units and multipliers: Lexoid emits
        # "13.9 \u00d7 compression", the PyMuPDF block sorter "13.9\u00d7 compression".
        # That splits one token in two and is not evidence of fabrication. The NUMBER is
        # the signal, so fall back to requiring the numeric core with no other digit
        # adjacent — an invented 99.4 still fails, because 99.4 appears nowhere.
        core = re.match(r"\d+(?:\.\d+)?", token)
        if not core:
            return False
        return re.search(r"(?<![\d.])" + re.escape(core.group(0)) + r"(?![\d])", hay) is not None

    # A fabricated METRIC is the failure mode that actually moves a score, so every
    # numeric token must be present. Prose is allowed to be a paraphrase, so word
    # tokens only need to clear a majority.
    numeric = [t for t in tokens if any(ch.isdigit() for ch in t)]
    words = [t for t in tokens if t not in numeric]

    if numeric and not all(numeric_present(t) for t in numeric):
        return False
    if not words:
        return True
    return sum(1 for t in words if present(t)) / len(words) >= cutoff


def _article(word: str) -> str:
    return "An" if word[:1].lower() in "aeiou" else "A"


def _numbers_in(text: str) -> List[str]:
    return re.findall(r"\d+(?:\.\d+)?", text or "")


# ---------------------------------------------------------------- deterministic checks

def check_role_weights_sum(ctx: ValidationContext) -> List[Finding]:
    """A typo in ROLE_WEIGHTS would silently rescale every composite score."""
    out: List[Finding] = []
    for track, weights in ctx.role_weights.items():
        total = round(sum(weights.values()), 9)
        if total != 1.0:
            out.append(Finding(
                check="ROLE_WEIGHTS_SUM",
                severity=BLOCKING,
                message=f"ROLE_WEIGHTS['{track}'] sums to {total}, not 1.0. "
                        "The composite score for this track is mis-scaled.",
                evidence={"track": track, "sum": total, "weights": weights},
            ))
    return out


def check_pillar_bounds(ctx: ValidationContext) -> List[Finding]:
    out: List[Finding] = []
    for name, entry in (ctx.result.get("pillars") or {}).items():
        score = entry.get("score") if isinstance(entry, dict) else None
        if not isinstance(score, (int, float)):
            out.append(Finding("PILLAR_BOUNDS", BLOCKING,
                               f"Pillar '{name}' has a non-numeric score.",
                               {"pillar": name, "score": score}, name))
        elif not 0 <= score <= 20:
            out.append(Finding("PILLAR_BOUNDS", BLOCKING,
                               f"Pillar '{name}' scored {score}, outside the declared 0-20 range.",
                               {"pillar": name, "score": score}, name))

    for key, limit in (("structural_score", 100), ("content_score", 100), ("overall_score", 100)):
        value = ctx.result.get(key)
        if not isinstance(value, (int, float)) or not 0 <= value <= limit:
            out.append(Finding("SCORE_BOUNDS", BLOCKING,
                               f"'{key}' is {value}, outside 0-{limit}.",
                               {"field": key, "value": value}))
    return out


def check_cpi_fail_closed(ctx: ValidationContext) -> List[Finding]:
    """`acad_score = 4` when CPI is missing. Confirm the policy actually applied."""
    signals = ctx.result.get("extracted_signals") or {}
    det = ctx.result.get("deterministic_scores") or {}
    status = signals.get("cpi_status")
    academics = det.get("Academics")

    if status != "UNVERIFIED_MISSING" or not isinstance(academics, (int, float)):
        return []

    # The unverified baseline is 4, but the scorer adds spike bonuses on top of it
    # (JEE AIR, olympiad, scholarship, CP rating). Those are legitimate; what would be
    # wrong is the baseline never having been applied at all.
    bonus = 0
    if signals.get("jee_adv_air"):
        bonus += 3 if signals["jee_adv_air"] <= 200 else (2 if signals["jee_adv_air"] <= 500 else 0)
    for flag, points in (("has_top_scholarship", 3), ("has_olympiad", 2),
                         ("has_aea", 2), ("has_kvpy", 1), ("has_surge", 2)):
        if signals.get(flag):
            bonus += points
    cf = signals.get("cf_rating") or 0
    if cf >= 2000: bonus += 4
    elif cf >= 1800: bonus += 3
    elif cf >= 1600: bonus += 2

    ceiling = min(20, 4 + bonus)
    if academics > ceiling:
        return [Finding(
            "CPI_FAIL_CLOSED", BLOCKING,
            f"CPI is missing, so academics should not exceed the unverified baseline of 4 "
            f"plus {bonus} points of verifiable spikes (max {ceiling}), but it scored {academics}.",
            {"cpi_status": status, "academics": academics, "max_expected": ceiling},
            "Academics & CPI",
        )]
    return [Finding(
        "CPI_UNVERIFIED", INFO,
        "No CPI was found, so academics was scored from the unverified baseline. "
        "The score understates the candidate if a CPI exists but was not extracted.",
        {"academics": academics}, "Academics & CPI",
    )]


def check_branch_agreement(ctx: ValidationContext) -> List[Finding]:
    """Detected branch versus the Department field. Flag disagreement, do not pick one."""
    signals = ctx.result.get("extracted_signals") or {}
    resume = ctx.result.get("structured_resume") or {}
    detected = signals.get("branch")
    department = (resume.get("Department") or "").strip()
    if not detected or not department or detected == "OTHER":
        return []

    aliases = {
        "CSE": ["computer science"], "EE": ["electrical"], "MTH": ["mathematics", "mnc"],
        "SDS": ["statistics", "data science"], "ME": ["mechanical"], "CHE": ["chemical"],
        "MSE": ["materials"], "CE": ["civil"], "AE": ["aerospace"],
        "BSBE": ["biological", "bsbe"], "ECO": ["economics"],
    }
    expected = aliases.get(detected, [])
    dept_lower = department.lower()
    if expected and not any(a in dept_lower for a in expected):
        return [Finding(
            "BRANCH_AMBIGUOUS", WARNING,
            f"The branch was detected as {detected}, but the Department field reads "
            f"'{department}'. Branch match may be scored against the wrong discipline.",
            {"detected_branch": detected, "department": department},
            "Branch Match",
        )]
    return []


def check_por_detection_gap(ctx: ValidationContext) -> List[Finding]:
    """Tier 8 with PoR entries present is a detection gap, not an absence of leadership."""
    signals = ctx.result.get("extracted_signals") or {}
    resume = ctx.result.get("structured_resume") or {}
    entries = resume.get("Position of Responsibility") or []
    if signals.get("por_tier") != 8:
        return []
    if entries:
        titles = [
            " — ".join(x for x in [e.get("position"), e.get("organization")] if x)
            for e in entries[:3]
        ]
        return [Finding(
            "POR_OUTSIDE_TIER_LIST", INFO,
            f"{len(entries)} position(s) of responsibility were held outside the seven-tier "
            "Gymkhana hierarchy, which covers only posts the institute itself confers. The "
            "pillar therefore sits at the no-PoR floor even though a role was held. Assess "
            "these on span, resources and turnout. Do not describe the role as unlisted or "
            "invalid, and never advise this candidate to 'seek leadership roles'.",
            {"por_entries": titles, "por_tier": 8},
            "Leadership & PoR",
        )]
    return [Finding(
        "POR_GENUINELY_ABSENT", INFO,
        "No position of responsibility was found in the resume.",
        {"por_tier": 8}, "Leadership & PoR",
    )]


def check_unverified_companies(ctx: ValidationContext) -> List[Finding]:
    """
    A work-ex organisation absent from the KG. A coverage note, never a fault.

    The graph holds firms that recruit at IIT Kanpur. An employer outside it is simply
    one the campus has no record of, so the finding records its size where that is known
    and says nothing about the resume being wrong.
    """
    if ctx.kg is None:
        return []
    resume = ctx.result.get("structured_resume") or {}
    profiles = ctx.result.get("company_profiles") or {}
    out: List[Finding] = []
    for entry in resume.get("Work Experience") or []:
        org = (entry.get("organization") or "").split(",")[0].strip()
        if not org or ctx.kg.is_known(org):
            continue
        profile = profiles.get(org) or {}
        label = profile.get("label")
        sized = (
            f"Sized as: {label.lower()}."
            if label and profile.get("band") != "unrecognised"
            else "Not one this system could size from public information."
        )
        out.append(Finding(
            "UNVERIFIED_COMPANY", INFO,
            f"'{org}' has no campus recruiting record at IIT Kanpur. {sized} This affects "
            "recruiter matching only; it does not change the score.",
            {"organization": org, "size_band": profile.get("band") or "unknown"},
            "Work Experience",
        ))
    return out


def check_semantic_vs_corpus_divergence(ctx: ValidationContext) -> List[Finding]:
    """
    The Gemini qualitative score and the corpus-matching score rate the same pillars.
    A wide gap means a bad extraction or a bad judgement — never average it away silently.
    """
    bench = ctx.result.get("semantic_benchmarks") or {}
    corpus = bench.get("semantic_scores") or {}
    pillars = ctx.result.get("pillars") or {}
    project_label = get_track(ctx.track).project_pillar_label

    pairs = [
        ("Work Experience", "work_experience_score", "Work Experience"),
        (project_label, "projects_score", "Projects"),
        ("SCOPE Articulation", "scope_score", "SCOPE Articulation"),
    ]
    out: List[Finding] = []
    THRESHOLD = 7
    for pillar_key, corpus_key, label in pairs:
        entry = pillars.get(pillar_key)
        llm_score = entry.get("score") if isinstance(entry, dict) else None
        corpus_score = corpus.get(corpus_key)
        if not isinstance(llm_score, (int, float)) or not isinstance(corpus_score, (int, float)):
            continue
        gap = abs(llm_score - corpus_score)
        if gap >= THRESHOLD:
            out.append(Finding(
                "SCORER_DIVERGENCE", WARNING,
                f"{label}: the qualitative evaluator scored {llm_score}/20 while corpus matching "
                f"scored {corpus_score}/20, a gap of {gap}. One of the two is reading this "
                "resume wrongly; the composite uses the qualitative score.",
                {"pillar": pillar_key, "llm_score": llm_score,
                 "corpus_score": corpus_score, "gap": gap},
                pillar_key,
            ))
    return out


def check_semantic_contract(ctx: ValidationContext) -> List[Finding]:
    """
    `evaluate_semantic_with_safety_net` is documented to raise rather than fabricate.
    If the result carries its sanitiser's default reasoning across all three pillars,
    the call almost certainly produced an empty body that was silently filled in.
    """
    pillars = ctx.result.get("pillars") or {}
    default = "Evaluated against track rubric."
    reasons = [
        (name, (entry or {}).get("reasoning"))
        for name, entry in pillars.items()
        if isinstance(entry, dict) and entry.get("reasoning") is not None
    ]
    if not reasons:
        return []
    defaulted = [name for name, text in reasons if (text or "").strip() == default]
    if len(defaulted) == len(reasons) and len(reasons) >= 2:
        return [Finding(
            "SEMANTIC_SANITISER_DEFAULTS", WARNING,
            "Every qualitative pillar carries the sanitiser's placeholder reasoning, which "
            "suggests the model returned an empty or unparsed body that was filled with "
            "defaults rather than failing loudly.",
            {"pillars": defaulted},
        )]
    return []


# ---------------------------------------------------------------- LLM grounding checks

_GROUNDING_SYSTEM = (
    "You are a strict grounding auditor for a resume extraction pipeline. You are given "
    "the RAW text extracted from a candidate's PDF and a set of CLAIMS that a previous "
    "model asserted about that resume.\n\n"
    "For each claim, decide whether it is supported by the raw text. A claim is SUPPORTED "
    "if the raw text contains the same fact, allowing for reformatting, abbreviation, "
    "line-wrapping and punctuation differences. A claim is UNSUPPORTED if the fact simply "
    "is not present — an invented organisation, a date or metric that appears nowhere, or "
    "a number that contradicts the text.\n\n"
    "Be conservative: only mark UNSUPPORTED when you are confident the fact is absent. "
    "Do not mark a claim unsupported merely because the wording differs. Never invent "
    "claim ids that were not given to you."
)


def _collect_claims(resume: Dict[str, Any]) -> List[Dict[str, str]]:
    """Field-level claims that must be traceable to the source text."""
    claims: List[Dict[str, str]] = []
    add = lambda cid, kind, text: claims.append({"id": cid, "type": kind, "text": text})

    for i, acad in enumerate(resume.get("Academic Qualifications") or []):
        parts = [acad.get("degree"), acad.get("institution"), acad.get("year"), acad.get("grade")]
        text = " | ".join(str(p) for p in parts if p)
        if text:
            add(f"acad-{i}", "academic_row", text)

    for i, job in enumerate(resume.get("Work Experience") or []):
        if job.get("organization"):
            add(f"org-{i}", "organization",
                f"{job.get('organization')} — {job.get('role') or ''} ({job.get('duration') or ''})")
        for j, bullet in enumerate(job.get("description") or []):
            # Only bullets carrying a number are worth the audit budget: an invented
            # metric is the failure mode that actually moves a score.
            if _numbers_in(bullet):
                add(f"org-{i}-b{j}", "quantified_claim", bullet)

    for i, proj in enumerate(resume.get("Projects") or []):
        if proj.get("title"):
            add(f"proj-{i}", "project_title", str(proj.get("title")))
        for j, bullet in enumerate(proj.get("description") or []):
            if _numbers_in(bullet):
                add(f"proj-{i}-b{j}", "quantified_claim", bullet)

    for i, por in enumerate(resume.get("Position of Responsibility") or []):
        text = " — ".join(str(x) for x in [por.get("position"), por.get("organization")] if x)
        if text:
            add(f"por-{i}", "position", text)

    return claims


def check_extraction_grounding(ctx: ValidationContext) -> List[Finding]:
    """
    Every organisation, degree, CPI figure and quantified metric in `structured_resume`
    must trace back to `raw_markdown`. This is the #1 failure mode of PDF->JSON LLM
    extraction: invented dates, merged entries, fabricated metrics.

    Deterministic fuzzy matching runs first and settles most claims for free; only the
    residue goes to the model.
    """
    resume = ctx.result.get("structured_resume") or {}
    raw = ctx.raw_markdown or ""
    claims = _collect_claims(resume)
    if not claims:
        return []
    if not raw.strip():
        return [Finding("GROUNDING_NO_SOURCE", WARNING,
                        "No raw PDF text was available, so extracted fields could not be "
                        "traced back to the source.", {})]

    unresolved = [c for c in claims if not _fuzzy_contains(c["text"], raw)]
    verdicts: Dict[str, str] = {
        c["id"]: "SUPPORTED" for c in claims if c not in unresolved
    }

    def _finding_for(claim: Dict[str, str], note: str, confirmed: bool) -> Finding:
        quantified = claim["type"] == "quantified_claim"
        return Finding(
            "UNGROUNDED_EXTRACTION",
            # A fabricated metric is what actually moves a score, so a confirmed one
            # blocks. An unconfirmed match failure is a warning until audited.
            BLOCKING if (quantified and confirmed) else WARNING,
            f"{_article(claim['type'])} {claim['type'].replace('_', ' ')} in the extracted "
            f"resume could not be found "
            f"in the PDF text: \"{claim['text'][:160]}\". {note}".strip(),
            {"claim_id": claim["id"], "claim": claim["text"],
             "type": claim["type"], "confirmed_by_audit": confirmed},
        )

    findings: List[Finding] = []
    if not unresolved:
        pass
    elif ctx.use_llm:
        prompt = (
            "RAW RESUME TEXT:\n"
            f"{raw[:24000]}\n\n"
            "CLAIMS TO AUDIT:\n"
            f"{json.dumps(unresolved, indent=2)}\n\n"
            'Return JSON: {"verdicts": [{"id": "<claim id>", '
            '"verdict": "SUPPORTED" | "UNSUPPORTED", "note": "<short reason>"}]}'
        )
        try:
            data = generate_json(prompt=prompt, system_instruction=_GROUNDING_SYSTEM,
                                 api_key=ctx.api_key, stage="grounding", temperature=0.0)
            by_id = {c["id"]: c for c in unresolved}
            seen = set()
            for v in data.get("verdicts") or []:
                cid = v.get("id")
                if cid not in by_id:
                    continue
                seen.add(cid)
                if str(v.get("verdict") or "").upper() == "SUPPORTED":
                    verdicts[cid] = "SUPPORTED"
                else:
                    verdicts[cid] = "UNSUPPORTED"
                    findings.append(_finding_for(by_id[cid],
                                                 str(v.get("note") or "").strip(), True))
            # A claim the auditor declined to rule on stays unresolved rather than
            # being quietly promoted to supported.
            for cid, claim in by_id.items():
                if cid not in seen:
                    verdicts[cid] = "UNSUPPORTED"
                    findings.append(_finding_for(
                        claim, "The grounding auditor returned no verdict for this claim.", False))
        except LLMError as exc:
            findings.append(Finding(
                "GROUNDING_UNAVAILABLE", WARNING,
                f"The grounding auditor could not run: {exc}. The claims below failed "
                "deterministic matching and were not confirmed either way.",
                {"unresolved": len(unresolved)},
            ))
            for c in unresolved:
                verdicts[c["id"]] = "UNSUPPORTED"
                findings.append(_finding_for(c, "Not confirmed — the auditor was unreachable.", False))
    else:
        # No auditor available. The deterministic matcher already found these absent, and
        # dropping that signal would let a fabricated claim through unremarked, so the
        # findings stand at WARNING with confirmed_by_audit = false.
        for c in unresolved:
            verdicts[c["id"]] = "UNSUPPORTED"
            findings.append(_finding_for(
                c, "Flagged by deterministic matching; no auditor was run to confirm it.", False))

    supported = sum(1 for v in verdicts.values() if v == "SUPPORTED")
    ctx.result.setdefault("_validation_internals", {})["grounding_coverage"] = (
        round(supported / len(claims), 4) if claims else 1.0
    )
    ctx.result["_validation_internals"]["claims_audited"] = len(claims)
    return findings


_REASONING_SYSTEM = (
    "You audit whether a scoring model's written justification is grounded. You are given "
    "the structured resume, the raw resume text, and one or more REASONING statements the "
    "scoring model wrote to justify a score.\n\n"
    "A statement is GROUNDED if everything factual it asserts (companies, technologies, "
    "metrics, roles, outcomes) appears in the resume or raw text. It is UNGROUNDED if it "
    "cites work, a metric, or an employer that does not appear anywhere.\n\n"
    "Generic evaluative language with no specific factual claim ('the projects show "
    "limited depth') is GROUNDED by default — it is a judgement, not a fact. Only flag "
    "invented specifics."
)


def check_reasoning_grounding(ctx: ValidationContext) -> List[Finding]:
    """The safety-net model must not invent justification for a score."""
    if not ctx.use_llm:
        return []
    pillars = ctx.result.get("pillars") or {}
    statements = [
        {"pillar": name, "reasoning": entry.get("reasoning")}
        for name, entry in pillars.items()
        if isinstance(entry, dict) and (entry.get("reasoning") or "").strip()
    ]
    if not statements:
        return []

    prompt = (
        "STRUCTURED RESUME:\n"
        f"{json.dumps(ctx.result.get('structured_resume') or {}, indent=2)[:14000]}\n\n"
        "RAW RESUME TEXT:\n"
        f"{(ctx.raw_markdown or '')[:12000]}\n\n"
        "REASONING STATEMENTS TO AUDIT:\n"
        f"{json.dumps(statements, indent=2)}\n\n"
        'Return JSON: {"verdicts": [{"pillar": "<pillar name>", '
        '"verdict": "GROUNDED" | "UNGROUNDED", "note": "<what was invented, if anything>"}]}'
    )
    try:
        data = generate_json(prompt=prompt, system_instruction=_REASONING_SYSTEM,
                             api_key=ctx.api_key, stage="reasoning-grounding", temperature=0.0)
    except LLMError as exc:
        return [Finding("REASONING_AUDIT_UNAVAILABLE", WARNING,
                        f"The qualitative reasoning could not be audited: {exc}", {})]

    known = {s["pillar"] for s in statements}
    out: List[Finding] = []
    for v in data.get("verdicts") or []:
        pillar = v.get("pillar")
        if pillar not in known:
            continue
        if str(v.get("verdict") or "").upper() == "UNGROUNDED":
            out.append(Finding(
                # A WARNING, not a critical finding. This audits the evaluator's WORDING,
                # not the candidate's claims: "the projects show C++ depth" when C++ is
                # in the skills list but not named in a project is loose prose, not an
                # invented fact. Fabricated numbers in the extraction are the serious case.
                "UNGROUNDED_REASONING", WARNING,
                f"The justification written for '{pillar}' is broader than the resume text "
                f"supports. {str(v.get('note') or '').strip()}",
                {"pillar": pillar, "reasoning": pillars[pillar].get("reasoning")},
                pillar,
            ))
    return out


# ---------------------------------------------------------------- registry

CHECKS: List[Callable[[ValidationContext], List[Finding]]] = [
    check_role_weights_sum,
    check_pillar_bounds,
    check_cpi_fail_closed,
    check_branch_agreement,
    check_por_detection_gap,
    check_unverified_companies,
    check_semantic_vs_corpus_divergence,
    check_semantic_contract,
    check_extraction_grounding,
    check_reasoning_grounding,
]


def validate(
    result: Dict[str, Any],
    *,
    track: str,
    raw_markdown: str,
    role_weights: Dict[str, Dict[str, float]],
    api_key: Optional[str] = None,
    kg: Any = None,
    use_llm: bool = True,
) -> Dict[str, Any]:
    ctx = ValidationContext(
        result=result, track=track, raw_markdown=raw_markdown,
        api_key=api_key, role_weights=role_weights, kg=kg, use_llm=use_llm,
    )

    findings: List[Finding] = []
    checks_run, checks_failed = [], []

    for check in CHECKS:
        name = check.__name__
        try:
            findings.extend(check(ctx) or [])
            checks_run.append(name)
        except Exception as exc:  # one broken check must not take down the report
            logger.exception("validation check %s raised", name)
            checks_failed.append(name)
            findings.append(Finding(
                "CHECK_CRASHED", WARNING,
                f"The validation check '{name}' failed to run: {exc}",
                {"check": name},
            ))

    severities = {f.severity for f in findings}
    if CRITICAL in severities:
        status = STATUS_REVIEW
    elif WARNING in severities:
        status = STATUS_WARN
    else:
        status = STATUS_PASS

    internals = result.pop("_validation_internals", {})

    return {
        "status": status,
        "findings": [f.to_dict() for f in findings],
        "grounding_coverage": internals.get("grounding_coverage"),
        "claims_audited": internals.get("claims_audited", 0),
        "counts": {
            # "blocking" is kept as the key name for payload compatibility; nothing blocks.
            "blocking": sum(1 for f in findings if f.severity == CRITICAL),
            "critical": sum(1 for f in findings if f.severity == CRITICAL),
            "warning": sum(1 for f in findings if f.severity == WARNING),
            "info": sum(1 for f in findings if f.severity == INFO),
        },
        "checks_run": checks_run,
        "checks_failed": checks_failed,
        "llm_used": use_llm,
        "agent_version": "validation-agent-v1",
    }
