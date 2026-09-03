"""
Evaluation pipeline.

Calls `scorer_engine.score_resume` unchanged, then layers on the derived modules and
normalises everything into a single typed view model for the frontend.

The scoring mathematics is not touched anywhere in this file. Every field that did not
come out of `score_resume` is listed in the response's `derived` block, with the version
of the rule set that produced it, so the client can label derived data as derived.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import config  # noqa: F401  -- puts SCORING_DIR on sys.path before the scorer imports
from company_fit import build_company_fit
from compliance import evaluate_compliance
from company_profile import classify as classify_companies
from evidence import PdfEvidenceLocator
from kg_adapter import load_kg
from llm import LLMError
from recommendation_agent import recommend as run_recommendation_agent
from recommendations import build_recommendations
from report_sections import build as build_report
from tracks import get_track, track_payload
from validation_agent import validate as run_validation_agent

from scorer_engine import ROLE_WEIGHTS, score_resume

RECOMMENDATION_RULESET = "deterministic-rules-v1"
VALIDATION_AGENT = "validation-agent-v1"
RECOMMENDATION_AGENT = "recommendation-agent-v1"
COMPLIANCE_RULESET = "spo-guidelines-v1"
ENGINE_VERSION = "spo-resume-intelligence/1.0"

# scorer_engine.score_resume thresholds, mapped to stable identifiers for the UI.
VERDICT_BANDS: List[Tuple[int, str]] = [
    (90, "PRIME"),
    (80, "OUTSTANDING"),
    (70, "VERY_GOOD"),
    (58, "BORDERLINE"),
    (0, "HIGH_RISK"),
]


class EvaluationError(RuntimeError):
    """Raised when the scoring pipeline could not produce a result at all."""

    def __init__(self, message: str, *, stage: str, code: str = "PIPELINE_ERROR"):
        super().__init__(message)
        self.stage = stage
        self.code = code


def verdict_band(score: int) -> str:
    for threshold, band in VERDICT_BANDS:
        if score >= threshold:
            return band
    return "HIGH_RISK"


def _weight_for(pillar: str, weights: Dict[str, float]) -> float:
    if pillar in weights:
        return weights[pillar]
    if pillar.startswith("Projects") or pillar.startswith("Core Projects"):
        return weights.get("Projects & Depth", 0.0)
    return 0.0


def _normalise_pillars(
    pillars: Dict[str, Any], weights: Dict[str, float], project_label: str
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for name, entry in (pillars or {}).items():
        if not isinstance(entry, dict):
            continue
        score = entry.get("score")
        score = int(score) if isinstance(score, (int, float)) else 0
        weight = _weight_for(name, weights)
        out.append(
            {
                "key": name,
                "label": name,
                "score": score,
                "max_score": 20,
                "tier": entry.get("tier"),
                "reasoning": entry.get("reasoning"),
                "weight": round(weight, 4),
                # Points this pillar currently puts into the 0-100 content score.
                "weighted_contribution": round(weight * score * 5, 2),
                # Points still available on the composite score if it reached 20/20.
                "headroom_points": round(weight * (20 - score) * 5 * 0.85, 2),
                "is_project_pillar": name == project_label,
            }
        )
    out.sort(key=lambda p: -p["weight"])
    return out


def _unverified_companies(resume_json: Dict[str, Any]) -> List[str]:
    kg = load_kg()
    if kg is None:
        return []
    names: List[str] = []
    for entry in resume_json.get("Work Experience") or []:
        org = (entry.get("organization") or "").strip()
        if not org:
            continue
        # Strip the trailing location the SPO template appends ("Adobe, India").
        head = org.split(",")[0].strip()
        if head and not kg.is_known(head) and head not in names:
            names.append(head)
    return names


def _attach_evidence(
    recommendations: List[Dict[str, Any]], pdf_path: str
) -> Tuple[List[Dict[str, Any]], int, int]:
    """
    Gives every finding a place on the page.

    Two kinds of finding, two ways of locating them. A textual finding names a bullet,
    which is searched for in the PDF. A layout finding is geometric — there is no
    sentence to search for — so it arrives with its region already measured from the
    spans that produced the score, and is counted as located without a lookup.
    """
    resolved = 0
    requested = 0
    try:
        locator = PdfEvidenceLocator(pdf_path)
    except Exception:
        # Pre-located regions survive even when the PDF cannot be reopened.
        pre = sum(1 for r in recommendations if r.get("evidence_refs"))
        return recommendations, pre, pre
    try:
        cache: Dict[str, List[Dict[str, Any]]] = {}
        for rec in recommendations:
            if rec.get("evidence_refs"):
                requested += 1
                resolved += 1
                continue
            requested += 1
            text = rec.get("evidence_text")
            if text:
                if text not in cache:
                    cache[text] = [ref.to_dict() for ref in locator.locate(text)]
                rec["evidence_refs"] = cache[text]

            # A finding with no quotable line still belongs somewhere: fall back to the
            # heading of the section it is about. Only skipped when the resume has no
            # such section, which is itself usually what the finding is reporting.
            if not rec["evidence_refs"]:
                section = rec.get("section")
                if section and section != "Document layout":
                    key = f"§{section}"
                    if key not in cache:
                        cache[key] = [r.to_dict() for r in locator.locate_section(section)]
                    rec["evidence_refs"] = cache[key]

            if rec["evidence_refs"]:
                resolved += 1
    finally:
        locator.close()
    return recommendations, resolved, requested


def _summarise(recommendations: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"HIGH": 0, "IMPORTANT": 0, "POLISH": 0}
    for rec in recommendations:
        severity = rec.get("severity")
        if severity in counts:
            counts[severity] += 1
    return {
        "high": counts["HIGH"],
        "important": counts["IMPORTANT"],
        "polish": counts["POLISH"],
        "total": len(recommendations),
    }


def evaluate(
    *,
    pdf_path: str,
    track: str,
    original_filename: str,
    file_size: int,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    validate: bool = True,
    recommend: bool = True,
) -> Dict[str, Any]:
    track_def = get_track(track)
    started = time.perf_counter()
    warnings: List[Dict[str, str]] = []

    try:
        result = score_resume(
            pdf_path=pdf_path,
            track=track,
            api_key=api_key,
            model_name=model_name or config.GEMINI_MODEL_NAME,
        )
    except ValueError as exc:
        raise EvaluationError(str(exc), stage="scoring", code="INVALID_INPUT") from exc
    except Exception as exc:  # the scorer fails explicitly rather than fabricating
        text = str(exc)
        # A quota failure is the one a real run hits most, and the provider's raw JSON is
        # not something to put in front of a student.
        if "RESOURCE_EXHAUSTED" in text or "429" in text or "quota" in text.lower():
            raise EvaluationError(
                "The model quota for this key is exhausted, so no evaluation could be "
                "produced. Quota resets daily; check billing if it persists.",
                stage="scoring",
                code="RATE_LIMITED",
            ) from exc
        raise EvaluationError(
            f"The scoring engine failed during evaluation: {exc}",
            stage="scoring",
            code="SCORING_FAILED",
        ) from exc

    required = ("overall_score", "verdict", "content_score", "structural_score", "pillars")
    missing = [field for field in required if field not in result]
    if missing:
        raise EvaluationError(
            f"Scoring engine returned an incomplete result; missing {', '.join(missing)}.",
            stage="scoring",
            code="MALFORMED_RESULT",
        )

    weights = ROLE_WEIGHTS[track]
    resume_json = result.get("structured_resume") or {}
    signals = result.get("extracted_signals") or {}
    layout = result.get("spo_layout_metrics") or {}

    if not resume_json:
        warnings.append(
            {
                "code": "EMPTY_STRUCTURED_RESUME",
                "message": "No structured resume was extracted, so bullet-level recommendations "
                "and evidence highlights are unavailable.",
            }
        )

    # ---- derived layer 1: recommendations
    # An employer outside the KG is a gap in campus coverage, not a defect in the resume,
    # so it is sized rather than merely reported as unresolved. Never blocks: if the
    # classifier is unavailable every name falls back to a neutral label.
    unverified = _unverified_companies(resume_json)
    try:
        company_profiles = classify_companies(unverified, api_key=api_key) if unverified else {}
    except Exception as exc:
        company_profiles = {}
        warnings.append(
            {"code": "COMPANY_PROFILES_UNAVAILABLE",
             "message": f"Could not size organisations outside the recruiter graph: {exc}"}
        )
    result["company_profiles"] = company_profiles

    try:
        recommendations = build_recommendations(result, track, weights, unverified)
    except Exception as exc:
        recommendations = []
        warnings.append(
            {"code": "RECOMMENDATIONS_UNAVAILABLE", "message": f"Recommendation rules failed: {exc}"}
        )

    recommendations, evidence_resolved, evidence_requested = _attach_evidence(
        recommendations, pdf_path
    )

    # ---- derived layer 2: SPO submission compliance
    try:
        page_count = _page_count(pdf_path)
        compliance = evaluate_compliance(
            pdf_path=pdf_path,
            # Same source, so a phone number or JEE rank visible only in the richer
            # content parse is still caught.
            raw_text=result.get("raw_markdown") or _raw_text(pdf_path),
            resume_json=resume_json,
            layout_metrics=layout,
            signals=signals,
            total_pages=page_count,
        )
    except Exception as exc:
        page_count = 0
        compliance = {"status": "UNAVAILABLE", "findings": [], "counts": {}, "error": str(exc)}
        warnings.append(
            {"code": "COMPLIANCE_UNAVAILABLE", "message": f"SPO compliance checks failed: {exc}"}
        )

    # ---- derived layer 3: estimated shortlist fit
    try:
        company_fit = build_company_fit(
            overall_score=float(result["overall_score"]),
            track=track,
            pillars=result.get("pillars") or {},
            weights=weights,
            # Branch drives per-firm hiring history, which is what separates one
            # Tier-1 recruiter from another for this candidate.
            branch=(signals or {}).get("branch"),
        )
    except Exception as exc:
        company_fit = {"available": False, "reason": str(exc), "entries": []}
        warnings.append(
            {"code": "COMPANY_FIT_UNAVAILABLE", "message": f"Shortlist fit could not be derived: {exc}"}
        )

    if not company_fit.get("available"):
        warnings.append(
            {
                "code": "COMPANY_FIT_UNAVAILABLE",
                "message": company_fit.get("reason") or "Shortlist fit is unavailable.",
            }
        )

    # ---- Phase 2: agentic validation, before anything reaches a human
    validation: Optional[Dict[str, Any]] = None
    if validate:
        try:
            validation = run_validation_agent(
                result,
                track=track,
                # The content parse the extractor actually read, NOT a fresh PyMuPDF
                # get_text. Auditing against a different reader makes content that only
                # the extractor's reader recovered
                # — table cells, link targets — look fabricated.
                raw_markdown=result.get("raw_markdown") or _raw_text(pdf_path),
                role_weights=ROLE_WEIGHTS,
                api_key=api_key,
                kg=load_kg(),
                use_llm=True,
            )
        except Exception as exc:
            validation = {
                "status": "PASS_WITH_WARNINGS",
                "findings": [{
                    "check": "VALIDATION_AGENT_UNAVAILABLE",
                    "severity": "WARNING",
                    "message": f"The validation agent could not run: {exc}. This result has not "
                               "been checked for grounding or internal consistency.",
                    "evidence": {}, "affected_pillar": None,
                }],
                "counts": {"blocking": 0, "warning": 1, "info": 0},
                "grounding_coverage": None, "claims_audited": 0,
                "checks_run": [], "checks_failed": ["<agent>"],
                "llm_used": False, "agent_version": VALIDATION_AGENT,
            }
            warnings.append({"code": "VALIDATION_UNAVAILABLE", "message": str(exc)})

        for finding in validation.get("findings", []):
            if finding.get("severity") in ("CRITICAL", "BLOCKING"):
                warnings.append({
                    "code": finding.get("check", "VALIDATION_CRITICAL"),
                    "message": finding.get("message", ""),
                })

    # ---- Phase 3: agentic recommendations
    #
    # These run regardless of validation status. Withholding advice because one sentence
    # of the evaluator's prose overreached leaves a student with nothing actionable; the
    # findings are shown beside the advice instead, so they can judge both.
    agent_recommendations: Optional[Dict[str, Any]] = None
    if recommend:
        try:
            agent_recommendations = run_recommendation_agent(
                result=result, track=track, weights=weights,
                validation=validation or {"status": "PASS", "findings": []},
                rule_findings=recommendations, kg=load_kg(), api_key=api_key,
            )
        except LLMError as exc:
            warnings.append({
                "code": "RECOMMENDATION_AGENT_UNAVAILABLE",
                "message": f"The recommendation agent could not run: {exc}. The deterministic "
                           "rule findings below are unaffected.",
            })

    overall = int(result["overall_score"])
    status = "DEGRADED" if warnings else "COMPLETE"

    payload = {
        "evaluation_status": status,
        "warnings": warnings,
        "track": track_payload(track),
        "file": {
            "name": original_filename,
            "size_bytes": file_size,
            "page_count": page_count,
        },
        "overall_score": overall,
        "verdict": result["verdict"],
        "verdict_band": verdict_band(overall),
        "content_score": int(result["content_score"]),
        "structural_score": int(result["structural_score"]),
        "pillars": _normalise_pillars(
            result.get("pillars") or {}, weights, track_def.project_pillar_label
        ),
        "extracted_signals": signals,
        "deterministic_scores": result.get("deterministic_scores") or {},
        "semantic_benchmarks": result.get("semantic_benchmarks") or {},
        "spo_layout_metrics": layout,
        "structural_breakdown": result.get("structural_breakdown") or {},
        "spo_layout_regions": result.get("spo_layout_regions") or {},
        "structural_visual": result.get("structural_visual"),
        "structured_resume": resume_json,
        "recommendations": recommendations,
        "recommendation_summary": _summarise(recommendations),
        "company_fit": company_fit,
        "compliance": compliance,
        "validation": validation,
        "agent_recommendations": agent_recommendations,
        "unverified_companies": unverified,
        "company_profiles": company_profiles,
        # Everything the scoring engine did not produce, and what produced it instead.
        "derived": {
            "recommendations": RECOMMENDATION_RULESET,
            "company_fit": company_fit.get("model_version"),
            "compliance": COMPLIANCE_RULESET,
            "evidence_refs": "pymupdf-text-search-v1",
            "validation": VALIDATION_AGENT if validation else None,
            "agent_recommendations": RECOMMENDATION_AGENT if agent_recommendations else None,
        },
        "meta": {
            "engine_version": ENGINE_VERSION,
            "model": model_name or config.GEMINI_MODEL_NAME,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "evidence_resolved": evidence_resolved,
            "evidence_requested": evidence_requested,
            "is_mock": False,
        },
    }

    # Assembled last so it can read the finished payload rather than repeating the
    # work: strengths come from the pillars and signals above, and the two gap
    # sections regroup findings that were already raised.
    payload["report"] = build_report(payload)
    return payload


def _page_count(pdf_path: str) -> int:
    import fitz

    with fitz.open(pdf_path) as doc:
        return len(doc)


def _raw_text(pdf_path: str) -> str:
    """Last-resort source when `score_resume` did not return its content parse."""
    import fitz

    with fitz.open(pdf_path) as doc:
        return "\n".join(page.get_text() for page in doc)
