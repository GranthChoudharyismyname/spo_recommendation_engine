#!/usr/bin/env python3
"""
Generates the demo fixture used by the frontend's mock service.

The resume is fictional and written for this purpose — no candidate data from the
signal corpora is used. Everything downstream of it is produced by the real modules:
the layout metrics come from `RelaxedResumeParser`, the hard signals from
`extract_deterministic_signals`, and the recommendations, compliance findings,
shortlist fit and evidence bounding boxes from the real derived layers running against
the real generated PDF.

Only the three Gemini-scored pillars are stand-ins, and the fixture marks itself
`meta.is_mock = true` so the UI can never present it as a real evaluation.

Usage:  python tools/make_mock_fixture.py
Writes: frontend/public/sample-resume.pdf
        frontend/src/mocks/mock-evaluation.json
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND / "app"), str(BACKEND / "scoring")]

import fitz  # noqa: E402

from company_fit import build_company_fit  # noqa: E402
from evidence_floors import apply_floors  # noqa: E402
from compliance import evaluate_compliance  # noqa: E402
from pipeline import _attach_evidence, _normalise_pillars, _summarise, _unverified_companies, verdict_band  # noqa: E402
from recommendation_agent import attribute_gap, critique, to_markdown  # noqa: E402
from recommendations import build_recommendations  # noqa: E402
from validation_agent import validate as run_validation  # noqa: E402
from resume_structure import RelaxedResumeParser  # noqa: E402
from scorer_engine import ROLE_WEIGHTS, extract_deterministic_signals  # noqa: E402
from tracks import get_track, track_payload  # noqa: E402

TRACK = "SDE"

RESUME = {
    "Name": "Ananya Deshmukh",
    "Department": "Computer Science and Engineering",
    "Contact Information": {
        "email": "ananya.d@iitk.ac.in",
        "phone": "+91 98765 43210",
        "linkedin": "linkedin.com/in/ananya-deshmukh",
        "github": "github.com/ananyad",
        "portfolio": "",
    },
    "Academic Qualifications": [
        {"degree": "B.Tech, Computer Science and Engineering", "institution": "Indian Institute of Technology Kanpur", "year": "2026", "grade": "CPI 8.42/10.0"},
        {"degree": "Intermediate/+2", "institution": "CBSE, Pune", "year": "2022", "grade": "94.20%"},
        {"degree": "Matriculation", "institution": "CBSE, Pune", "year": "2020", "grade": "95.80%"},
    ],
    "Scholastic Qualifications": [
        "All India Rank 1284 in JEE Advanced 2022",
        "Academic Excellence Award, IIT Kanpur, 2024",
        "Max rating 1712 (Expert) on Codeforces",
        "Finalist, Inter-IIT Tech Meet software track",
    ],
    "Work Experience": [
        {
            "organization": "Sprinklr, Gurugram",
            "role": "Software Development Intern",
            "duration": "May'25 - Jul'25",
            "description": [
                "Worked on the ingestion service for the social listening platform alongside the platform team",
                "Rewrote the batch deduplication stage as a streaming operator over Kafka, cutting end-to-end ingestion latency from 4.1s to 900ms across 12M daily events in production",
                "Added consumer-lag alerting and a replay path, which the on-call rotation adopted after the migration",
            ],
        },
        {
            "organization": "Tessellate Systems",
            "role": "Backend Engineering Intern",
            "duration": "Dec'24 - Jan'25",
            "description": [
                "Built REST endpoints for the merchant onboarding flow using FastAPI and PostgreSQL",
                "Migrated the reporting job to a task queue so the nightly run stopped blocking the web workers",
            ],
        },
    ],
    "Projects": [
        {
            "title": "Coalesce — a log-structured key-value store",
            "organization": "Self Project",
            "duration": "Jan'25 - Apr'25",
            "description": [
                "Designed an LSM-tree storage engine in C++20 with a write-ahead log, tiered compaction and a bloom-filter read path",
                "Benchmarked against LevelDB on a 40M-key workload, reaching 1.8x write throughput at comparable p99 read latency",
                "Open-sourced the engine with a fuzzing harness; the repository has been forked by other course teams",
            ],
        },
        {
            "title": "Distributed Consensus Visualiser",
            "organization": "CS425 Course Project | Prof. R. Iyer",
            "duration": "Aug'24 - Nov'24",
            "description": [
                "Implemented Raft leader election and log replication over a simulated lossy network",
                "Built a web front end that steps through the replicated log so the failure modes can be inspected",
            ],
        },
    ],
    "Research Experience": [],
    "Major Competitions": [
        {"competition": "Inter-IIT Tech Meet", "organization": "IIT Kanpur contingent", "achievement": "Finalist, software track", "year": "2024", "description": ["Shipped an offline-first field data collection tool judged on reliability under intermittent connectivity"]}
    ],
    "Position of Responsibility": [
        {"position": "Coordinator, Programming Club", "organization": "Students' Gymkhana, IIT Kanpur", "duration": "Apr'24 - Mar'25", "description": ["Ran the weekly contest series and the summer mentorship track for 180 first-year students"]}
    ],
    "Social Impact": [],
    "Extra Curricular Activities": [
        "Completed the Coursera Machine Learning specialization certificate",
        "Volunteer, campus open-source install fest",
    ],
    "Technical Skills": ["C++", "Python", "Go", "PostgreSQL", "Kafka", "Docker", "gRPC"],
    "Relevant Courses": ["Operating Systems", "Computer Networks", "Distributed Systems", "Database Systems", "Compilers"],
}

# Stand-in only for the three pillars scorer_engine sources from Gemini.
MOCK_SEMANTIC = {
    "work_experience_score": 13,
    "work_experience_tier": "Good",
    "work_experience_reasoning": "The Sprinklr internship shows a measured production latency improvement at real event volume. The second internship is described in terms of endpoints built rather than outcomes delivered.",
    "projects_score": 16,
    "projects_tier": "Very Good",
    "projects_reasoning": "The storage engine is a genuine systems project with a benchmark against a real baseline. The consensus visualiser stops at implementation and does not report what the evaluation showed.",
    "scope_articulation_score": 13,
    "scope_articulation_tier": "Good",
    "scope_articulation_reasoning": "Strong quantification in the Sprinklr and Coalesce bullets; several other lines name the technology without an outcome.",
}


def render_pdf(path: Path) -> None:
    """Renders the resume in the SPO single-column format, close to the real template."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4
    margin = 40.0
    x, y = margin, margin
    width = 595 - 2 * margin

    def write(text: str, size: float, bold: bool = False, gap: float = 3.0, indent: float = 0.0) -> None:
        """Wraps and draws a paragraph, advancing y by exactly what was drawn."""
        nonlocal y
        font = "tibo" if bold else "tiro"  # Times-Bold / Times-Roman (base-14)
        avail = width - indent
        words = text.split(" ")
        line, lines = "", []
        for word in words:
            trial = f"{line} {word}".strip()
            if fitz.get_text_length(trial, fontname=font, fontsize=size) <= avail:
                line = trial
            else:
                if line:
                    lines.append(line)
                line = word
        if line:
            lines.append(line)
        leading = size * 1.24
        for i, ln in enumerate(lines):
            # Continuation lines of a bullet hang under the text, not under the marker.
            hang = 9.0 if (i and text.lstrip().startswith("\u2022")) else 0.0
            page.insert_text(
                fitz.Point(x + indent + hang, y + leading * (i + 1) - size * 0.28),
                ln, fontsize=size, fontname=font, color=(0, 0, 0),
            )
        y += leading * len(lines) + gap

    def heading(text: str) -> None:
        nonlocal y
        y += 4
        write(text.upper(), 9.5, bold=True, gap=1.5)
        page.draw_line(fitz.Point(x, y - 1), fitz.Point(x + width, y - 1), width=0.5)
        y += 3

    write(RESUME["Name"], 19.0, bold=True, gap=2)
    contact = RESUME["Contact Information"]
    write(
        f"{RESUME['Department']}, IIT Kanpur  |  {contact['email']}  |  {contact['phone']}  |  {contact['github']}",
        8.5, gap=4,
    )

    heading("Academic Qualifications")
    for row in RESUME["Academic Qualifications"]:
        write(f"{row['year']}    {row['degree']}, {row['institution']}    {row['grade']}", 9.0, gap=1.5)

    heading("Scholastic Achievements")
    for item in RESUME["Scholastic Qualifications"]:
        write(f"•  {item}", 9.0, gap=1.5)

    heading("Work Experience")
    for job in RESUME["Work Experience"]:
        write(f"{job['role']}, {job['organization']}   ({job['duration']})", 9.0, bold=True, gap=1.5)
        for bullet in job["description"]:
            write(f"•  {bullet}", 9.0, gap=1.5, indent=10)

    heading("Key Projects")
    for proj in RESUME["Projects"]:
        write(f"{proj['title']}  |  {proj['organization']}   ({proj['duration']})", 9.0, bold=True, gap=1.5)
        for bullet in proj["description"]:
            write(f"•  {bullet}", 9.0, gap=1.5, indent=10)

    heading("Positions of Responsibility")
    for por in RESUME["Position of Responsibility"]:
        write(f"{por['position']}, {por['organization']}   ({por['duration']})", 9.0, bold=True, gap=1.5)
        for bullet in por["description"]:
            write(f"•  {bullet}", 9.0, gap=1.5, indent=10)

    heading("Technical Skills")
    write(", ".join(RESUME["Technical Skills"]), 9.0, gap=2)
    heading("Relevant Courses")
    write(", ".join(RESUME["Relevant Courses"]), 9.0, gap=2)
    heading("Extra-Curricular Activities")
    for item in RESUME["Extra Curricular Activities"]:
        write(f"•  {item}", 9.0, gap=1.5)

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()


def main() -> None:
    repo = BACKEND.parent
    pdf_path = repo / "frontend" / "public" / "sample-resume.pdf"
    out_path = repo / "frontend" / "src" / "mocks" / "mock-evaluation.json"

    render_pdf(pdf_path)

    with fitz.open(pdf_path) as doc:
        raw_text = "\n".join(p.get_text() for p in doc)
        page_count = len(doc)

    struct = RelaxedResumeParser(str(pdf_path)).eval_all()
    signals, det = extract_deterministic_signals(RESUME, raw_text, TRACK)

    # Evidence floors, exactly as score_resume applies them.
    we_floored, scope_floored, acad_floored, evidence_adjustments = apply_floors(
        work_experience_score=MOCK_SEMANTIC["work_experience_score"],
        scope_score=MOCK_SEMANTIC["scope_articulation_score"],
        signals=signals, academics_score=det.get("Academics"), track=TRACK,
    )
    if acad_floored is not None:
        det["Academics"] = acad_floored
    MOCK_SEMANTIC["work_experience_score"] = we_floored
    MOCK_SEMANTIC["scope_articulation_score"] = scope_floored

    proj_label = get_track(TRACK).project_pillar_label
    pillars = {
        "Academics & CPI": {"score": det["Academics"], "tier": "Very Good" if det["Academics"] >= 14 else "Good"},
        "Branch Match": {"score": det["Branch"], "tier": "Very Good"},
        "Work Experience": {"score": MOCK_SEMANTIC["work_experience_score"], "tier": MOCK_SEMANTIC["work_experience_tier"], "reasoning": MOCK_SEMANTIC["work_experience_reasoning"]},
        proj_label: {"score": MOCK_SEMANTIC["projects_score"], "tier": MOCK_SEMANTIC["projects_tier"], "reasoning": MOCK_SEMANTIC["projects_reasoning"]},
        "SCOPE Articulation": {"score": MOCK_SEMANTIC["scope_articulation_score"], "tier": MOCK_SEMANTIC["scope_articulation_tier"], "reasoning": MOCK_SEMANTIC["scope_articulation_reasoning"]},
        "Leadership & PoR": {"score": det["Leadership"], "tier": "Very Good" if det["Leadership"] >= 14 else "Average"},
    }

    weights = ROLE_WEIGHTS[TRACK]
    content = round(
        weights["Academics & CPI"] * pillars["Academics & CPI"]["score"] * 5
        + weights["Branch Match"] * pillars["Branch Match"]["score"] * 5
        + weights["Work Experience"] * pillars["Work Experience"]["score"] * 5
        + weights["Projects & Depth"] * pillars[proj_label]["score"] * 5
        + weights["SCOPE Articulation"] * pillars["SCOPE Articulation"]["score"] * 5
        + weights["Leadership & PoR"] * pillars["Leadership & PoR"]["score"] * 5
    )
    structural = struct["score"]
    overall = round(0.85 * content + 0.15 * structural)
    verdict = (
        "Top 1% Day-1 Prime (God-Tier Contender)" if overall >= 90
        else "Outstanding (Strong Shortlist Contender)" if overall >= 80
        else "Very Good (Shortlist Contender)" if overall >= 70
        else "Good / Borderline (Needs Optimization)" if overall >= 58
        else "High Risk (Requires Major Revision)"
    )

    result = {
        "overall_score": overall, "verdict": verdict, "content_score": content,
        "structural_score": structural, "extracted_signals": signals, "pillars": pillars,
        "spo_layout_metrics": struct["metrics"], "structured_resume": RESUME,
    }

    unverified = _unverified_companies(RESUME)
    recs = build_recommendations(result, TRACK, weights, unverified)
    recs, resolved, requested = _attach_evidence(recs, str(pdf_path))
    compliance = evaluate_compliance(str(pdf_path), raw_text, RESUME, struct["metrics"], signals, page_count)
    fit = build_company_fit(float(overall), TRACK, pillars, weights,
                            branch=signals.get("branch"))

    # ---- Phase 2: the real validation agent, deterministic checks only.
    # `use_llm=False` keeps fixture generation offline and reproducible; the grounding
    # pre-filter still runs, so the report is genuine, just unaudited by the model.
    validation = run_validation(
        {**result, "deterministic_scores": det, "semantic_benchmarks": {}},
        track=TRACK, raw_markdown=raw_text, role_weights=ROLE_WEIGHTS,
        kg=None, use_llm=False,
    )

    # ---- Phase 3: real attribution and a real critique pass over drafts written here to
    # stand in for the model's. Two of them deliberately break the hard rules, so the
    # fixture demonstrates the rejection path rather than only the happy one.
    attribution = attribute_gap(result, TRACK, weights)
    drafts = [
        {
            "id": "agent-workex-outcome", "severity": "HIGH", "pillar": "Work Experience",
            "section": "Work Experience",
            "issue": "The Tessellate internship names the stack but states no outcome.",
            "evidence_ref": "Built REST endpoints for the merchant onboarding flow using FastAPI and PostgreSQL",
            "suggested_action": "Say what the onboarding flow did once it shipped — the number of "
                                "merchants onboarded, or the step it removed. Use the figure you "
                                "already have from the handover; if none was recorded, state what "
                                "went live instead.",
            "expected_impact": "Work Experience, the pillar with the most headroom on SDE",
            "source_rule": "SCOPE_BULLET_INCOMPLETE",
        },
        {
            "id": "agent-consensus-eval", "severity": "IMPORTANT",
            "pillar": "Projects & Systems Depth", "section": "Projects",
            "issue": "The Raft project stops at implementation and never reports what the "
                     "evaluation showed.",
            "evidence_ref": "Implemented Raft leader election and log replication over a simulated lossy network",
            "suggested_action": "State the failure conditions you actually exercised — the loss "
                                "rate the cluster held quorum under, or the election latency you "
                                "measured in the simulator.",
            "expected_impact": "Projects & Systems Depth, up to +3.4",
            "source_rule": "PROJECT_DEPTH_BELOW_BAND",
        },
        {
            "id": "agent-certificate", "severity": "POLISH",
            "pillar": "Extra Curricular Activities", "section": "Extra Curricular Activities",
            "issue": "A MOOC completion certificate is competing for space with verifiable work.",
            "evidence_ref": "Completed the Coursera Machine Learning specialization certificate",
            "suggested_action": "Drop the certificate and give the line to the Coalesce benchmark "
                                "numbers, which are verifiable.",
            "expected_impact": "No direct score impact; frees a line",
            "source_rule": "KB_SDE_GENERIC_CERTIFICATE",
        },
        # --- these two must be rejected by the hard-rule gate
        {
            "id": "agent-fabricate", "severity": "IMPORTANT", "pillar": "SCOPE Articulation",
            "section": "Projects",
            "issue": "The consensus visualiser has no metric.",
            "evidence_ref": "Built a web front end that steps through the replicated log",
            "suggested_action": "Just add a 30% improvement metric so the bullet lands harder.",
            "expected_impact": "SCOPE Articulation",
            "source_rule": "AGENT_DERIVED",
        },
        {
            "id": "agent-ppo", "severity": "POLISH", "pillar": "Work Experience",
            "section": "Work Experience",
            "issue": "Pedigree could be stronger for Tier-1 desks.",
            "evidence_ref": "Software Development Intern, Sprinklr, Gurugram",
            "suggested_action": "Apply to Jane Street through the campus cycle to lift your "
                                "work-experience tier.",
            "expected_impact": "Work Experience",
            "source_rule": "AGENT_DERIVED",
        },
    ]
    kept, rejected = critique(
        drafts=drafts, validation=validation,
        blocked_companies=["Jane Street", "Citadel", "Optiver"],
        resume=RESUME, api_key=None,
    )
    agent_recommendations = {
        "agent_version": "recommendation-agent-v1",
        "attribution": attribution,
        "recommendations": kept,
        "rejected": rejected,
        "counts": {
            "drafted": len(drafts), "kept": len(kept), "rejected": len(rejected),
            "rejected_by_code": sum(1 for r in rejected if r.get("rejected_by") == "code"),
            "rejected_by_critique": sum(1 for r in rejected if r.get("rejected_by") == "critique"),
        },
        "blocked_companies_considered": ["Jane Street", "Citadel", "Optiver"],
        "markdown": to_markdown(result=result, track=TRACK, attribution=attribution,
                                recommendations=kept),
    }

    fixture = {
        "evaluation_status": "COMPLETE",
        "warnings": [],
        "track": track_payload(TRACK),
        "file": {"name": "sample-resume.pdf", "size_bytes": pdf_path.stat().st_size, "page_count": page_count},
        "overall_score": overall, "verdict": verdict, "verdict_band": verdict_band(overall),
        "content_score": content, "structural_score": structural,
        "pillars": _normalise_pillars(pillars, weights, proj_label),
        "extracted_signals": signals, "deterministic_scores": det, "semantic_benchmarks": {},
        "spo_layout_metrics": struct["metrics"], "structured_resume": RESUME,
        "recommendations": recs, "recommendation_summary": _summarise(recs),
        "company_fit": fit, "compliance": compliance,
        "validation": validation, "agent_recommendations": agent_recommendations,
        "evidence_adjustments": evidence_adjustments,
        "unverified_companies": unverified,
        "derived": {
            "recommendations": "deterministic-rules-v1",
            "company_fit": fit.get("model_version"),
            "compliance": "spo-guidelines-v1",
            "evidence_refs": "pymupdf-text-search-v1",
            "validation": "validation-agent-v1",
            "agent_recommendations": "recommendation-agent-v1",
        },
        "meta": {
            "engine_version": "spo-resume-intelligence/1.0",
            "model": "mock (no model call)",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": 0,
            "evidence_resolved": resolved, "evidence_requested": requested,
            "is_mock": True,
            "mock_note": "Fictional resume. Layout metrics, hard signals, recommendations, compliance findings, shortlist fit and PDF evidence coordinates are all produced by the real modules against the bundled sample PDF. Only the three Gemini-scored pillars are stand-in values.",
        },
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(fixture, indent=2))
    print(f"PDF      -> {pdf_path}  ({page_count} page, {pdf_path.stat().st_size} bytes)")
    print(f"Fixture  -> {out_path}")
    print(f"Score    :  {overall}/100  {verdict}")
    print(f"Structural: {structural}/100   Content: {content}/100")
    print(f"Recs     :  {len(recs)}   evidence resolved {resolved}/{requested}")
    print(f"Compliance: {compliance['status']} {compliance['counts']}")
    sch = signals.get("scholastic_summary") or {}
    print(f"Scholastic: {sch.get('total', 0)} signals, strongest={sch.get('strongest_tier')}")
    print(f"Floors    : {len(evidence_adjustments)} applied "
          f"{[(a['pillar'], a['from'], a['to']) for a in evidence_adjustments]}")
    print(f"Validation: {validation['status']} {validation['counts']} "
          f"grounding={validation['grounding_coverage']}")
    c = agent_recommendations["counts"]
    print(f"Agent     : drafted {c['drafted']}, kept {c['kept']}, rejected {c['rejected']} "
          f"({c['rejected_by_code']} by hard rule)")


if __name__ == "__main__":
    main()
