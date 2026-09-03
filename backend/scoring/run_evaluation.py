#!/usr/bin/env python3
"""
ResuMetr — CLI runner.

    python run_evaluation.py resume.pdf --track SDE \
        --validate --recommend \
        --json_out results.json --md_out review.md

Layers
    1-5  scoring pipeline (resume_structure, resume_parser, scorer_engine)
    6    validation agent   (--validate)
    7    recommendation agent (--recommend)

Exit codes
    0  evaluation produced; validation findings, if any, are printed with it
    1  the pipeline itself failed (bad path, model unreachable, malformed result)
    2  --strict was passed and validation raised a critical finding

A critical finding never withholds the result. The score, the findings and the
recommendations are all printed; --strict only changes the exit code, for callers that
want to gate on it in CI.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# The API adapter package holds the agents, the canonical track registry and the config.
_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND / "app"))
sys.path.insert(0, str(_BACKEND / "scoring"))

import config  # noqa: E402
from kg_adapter import load_kg  # noqa: E402
from llm import LLMError  # noqa: E402
from recommendation_agent import recommend as run_recommendation_agent  # noqa: E402
from recommendations import build_recommendations  # noqa: E402
from tracks import TRACK_CODES  # noqa: E402
from validation_agent import validate as run_validation_agent  # noqa: E402

from scorer_engine import ROLE_WEIGHTS, score_resume  # noqa: E402

EXIT_OK, EXIT_ERROR, EXIT_STRICT_FAIL = 0, 1, 2

SEVERITY_MARK = {"CRITICAL": "✗", "BLOCKING": "✗", "WARNING": "!", "INFO": "·"}


def _raw_text(pdf_path: str) -> str:
    """Fallback only. `score_resume` returns the content parse it actually used."""
    import fitz
    with fitz.open(pdf_path) as doc:
        return "\n".join(page.get_text() for page in doc)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="run_evaluation.py",
        description="ResuMetr — IIT Kanpur resume evaluation pipeline",
    )
    parser.add_argument("pdf_path", type=str, help="Path to the resume PDF")
    # Choices come from the canonical registry, never a second hardcoded list.
    parser.add_argument("--track", type=str, default="SDE", choices=TRACK_CODES,
                        help="Target placement track")
    parser.add_argument("--api_key", type=str, default=None,
                        help="Gemini API key (or set GEMINI_API_KEY)")
    parser.add_argument("--model", type=str, default=None,
                        help=f"Model name (default: {config.GEMINI_MODEL_NAME})")
    parser.add_argument("--validate", action="store_true",
                        help="Run the validation agent")
    parser.add_argument("--strict", action="store_true",
                        help="Exit 2 if validation raises a critical finding. The result "
                             "is still printed in full.")
    parser.add_argument("--recommend", action="store_true",
                        help="Run the recommendation agent")
    parser.add_argument("--json_out", type=str, default=None,
                        help="Write the full result as JSON")
    parser.add_argument("--md_out", type=str, default=None,
                        help="Write the human-readable review as Markdown")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress the section dumps; print the summary only")
    args = parser.parse_args()

    if not os.path.exists(args.pdf_path):
        print(f"Error: file not found: {args.pdf_path}", file=sys.stderr)
        return EXIT_ERROR

    if args.model:
        config.GEMINI_MODEL_NAME = args.model

    print()
    print("  ResuMetr — IIT Kanpur resume evaluation")
    print(f"  File   : {args.pdf_path}")
    print(f"  Track  : {args.track}")
    print(f"  Model  : {config.GEMINI_MODEL_NAME}")
    print("  " + "-" * 56)

    try:
        result = score_resume(
            pdf_path=args.pdf_path,
            track=args.track,
            api_key=args.api_key,
            model_name=config.GEMINI_MODEL_NAME,
        )
    except Exception as exc:
        print(f"Pipeline error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if not args.quiet:
        print("\n=== PART 1: PHYSICAL STRUCTURE ===")
        print(json.dumps(result["spo_layout_metrics"], indent=2))
        print(f"Structural score: {result['structural_score']} / 100")
        print("\n=== PART 2: STRUCTURED RESUME ===")
        print(json.dumps(result["structured_resume"], indent=2))
        print("\n=== PART 3: DETERMINISTIC HARD SIGNALS ===")
        print(json.dumps(result["extracted_signals"], indent=2))
        print("\n=== PART 4: SEMANTIC BENCHMARK MATCHING ===")
        print(json.dumps(result.get("semantic_benchmarks", {}), indent=2))
        print("\n=== PART 5: PILLARS ===")
        print(json.dumps(result["pillars"], indent=2))

    print("\n=== PART 6: COMPOSITE SCORE ===")
    print(f"  OVERALL         : {result['overall_score']} / 100")
    print(f"  VERDICT         : {result['verdict']}")
    print(f"  CONTENT   (85%) : {result['content_score']} / 100")
    print(f"  STRUCTURE (15%) : {result['structural_score']} / 100")

    weights = ROLE_WEIGHTS[args.track]
    kg = load_kg()
    validation = None
    agent_output = None

    # ---- Layer 6
    if args.validate:
        print("\n=== PART 7: VALIDATION AGENT ===")
        try:
            validation = run_validation_agent(
                result, track=args.track,
                raw_markdown=result.get("raw_markdown") or _raw_text(args.pdf_path),
                role_weights=ROLE_WEIGHTS, api_key=args.api_key, kg=kg, use_llm=True,
            )
        except Exception as exc:
            print(f"Validation agent error: {exc}", file=sys.stderr)
            return EXIT_ERROR

        result["validation"] = validation
        coverage = validation.get("grounding_coverage")
        print(f"  STATUS   : {validation['status']}")
        print(f"  GROUNDING: {f'{coverage:.0%}' if coverage is not None else 'n/a'} "
              f"of {validation.get('claims_audited', 0)} extracted claims traced to the PDF")
        counts = validation.get("counts", {})
        print(f"  FINDINGS : {counts.get('blocking',0)} blocking, "
              f"{counts.get('warning',0)} warning, {counts.get('info',0)} info")
        for f in validation.get("findings", []):
            mark = SEVERITY_MARK.get(f.get("severity"), "·")
            print(f"    {mark} [{f.get('check')}] {f.get('message')}")

        if validation["status"] == "NEEDS_REVIEW":
            # Reported, never withheld: the findings sit beside the score rather than
            # replacing it, so a reviewer can weigh both.
            print("\n  NEEDS REVIEW — the findings above should be checked against the "
                  "PDF before this result is relied on.", file=sys.stderr)

    # ---- Layer 7
    if args.recommend:
        print("\n=== PART 8: RECOMMENDATION AGENT ===")
        try:
            rule_findings = build_recommendations(result, args.track, weights, [])
            agent_output = run_recommendation_agent(
                result=result, track=args.track, weights=weights,
                validation=validation or {"status": "PASS", "findings": []},
                rule_findings=rule_findings, kg=kg, api_key=args.api_key,
            )
        except (LLMError, ValueError) as exc:
            print(f"Recommendation agent error: {exc}", file=sys.stderr)
            return EXIT_ERROR

        result["agent_recommendations"] = agent_output
        c = agent_output["counts"]
        print(f"  DRAFTED  : {c['drafted']}")
        print(f"  KEPT     : {c['kept']}")
        print(f"  REJECTED : {c['rejected']} "
              f"({c['rejected_by_code']} by hard rule, {c['rejected_by_critique']} by critique)")
        for r in agent_output.get("rejected", []):
            print(f"    ✗ {r.get('issue', r.get('id'))} — {r.get('rejection_reason')}")
        print()
        print(agent_output["markdown"])

        if args.md_out:
            Path(args.md_out).write_text(agent_output["markdown"])
            print(f"\nMarkdown review written to {args.md_out}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, indent=2))
        print(f"\nFull result written to {args.json_out}")

    if args.strict and validation and validation.get("status") == "NEEDS_REVIEW":
        return EXIT_STRICT_FAIL
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
