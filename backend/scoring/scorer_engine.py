"""
IIT Kanpur Resume Scoring Engine
================================
Modular Architecture integrating:
  1. Module A: Resume Parsing Agent with 2D Block Spatial Extraction (resume_parser.py)
  2. Module Structure: SPO Relaxed Resume Parser & Layout Metric Engine (resume_structure.py)
  3. Module B: Deterministic Hard Signals & Positive Signal Benchmarks (Multi-Track)
  4. Module C: Gemini Qualitative Safety Net & Evaluator
"""

import os
import re
import json
from typing import Dict, Any, Tuple, Optional

from resume_parser import markdown_to_resume_json, extract_pdf_markdown
from resume_structure import RelaxedResumeParser
from semantic_signal_matcher import match_candidate_against_signal_corpus

try:
    from google import genai
    from google.genai import types
    HAS_NEW_GENAI = True
except ImportError:
    import google.generativeai as legacy_genai
    HAS_NEW_GENAI = False


# ------------------------------------------------------------------
# Knowledge-graph adapter. Optional at import time so the scoring modules stay usable
# standalone; when it is unavailable every organisation is simply reported as unverified
# rather than silently scored against a stale hardcoded list.
# ------------------------------------------------------------------
def _shared_transport():
    """
    The project's LLM transport, when the app layer is importable.

    Only the transport is shared — model chain, deadline and retry policy. The prompt,
    the JSON schema and the sanitiser are this module's own and are untouched, so the
    extracted signal keeps the shape the corpora were built against.
    """
    try:
        from llm import generate_text
    except ImportError:
        return None
    return generate_text


# ------------------------------------------------------------------
def _evidence_floors(work_experience_score, scope_score, signals,
                     academics_score=None, track=None):
    """Deterministic floors from the KG and quantified impact. Optional at import time."""
    try:
        from evidence_floors import apply_floors
    except ImportError:
        return work_experience_score, scope_score, academics_score, []
    try:
        return apply_floors(work_experience_score=work_experience_score,
                            scope_score=scope_score, signals=signals,
                            academics_score=academics_score, track=track)
    except Exception:
        return work_experience_score, scope_score, academics_score, []


def _role_framework(track: str) -> str:
    """
    The full IITK evaluation framework for a track, appended to the qualitative
    evaluator's system prompt as supporting context.

    ROLE_RUBRICS still leads the prompt and defines the bands; the framework tells the
    model where inside a band a candidate falls, using the same article the signal
    corpora were labelled against. Optional at import time and silent when absent, so
    the pipeline runs unchanged without the knowledge base.
    """
    try:
        from role_frameworks import prompt_section
    except ImportError:
        return ""
    try:
        return prompt_section(track)
    except Exception:
        return ""


def _scholastic(resume_json, raw_text):
    """Tiered scholastic signals. Optional at import time."""
    try:
        from scholastic_signals import extract_scholastic_signals
    except ImportError:
        return None
    try:
        return extract_scholastic_signals(resume_json, raw_text)
    except Exception:
        return None


def _quantified_impact(resume_json):
    """Quantified results in the corpora's `impact` shape. Optional at import time."""
    try:
        from impact_signals import extract_impact_signals
    except ImportError:
        return None
    try:
        return extract_impact_signals(resume_json)
    except Exception:
        return None


def _kg_pedigree(name: str, track: str):
    try:
        from kg_adapter import load_kg
    except ImportError:
        return None
    kg = load_kg()
    if kg is None:
        return None
    try:
        return kg.get_pedigree_tier(name, track)
    except Exception:
        return None


# ============================================================
# 1. ROLE DEFINITIONS & RUBRIC REGISTRY
# ============================================================

ROLE_RUBRICS = {
    "ANALYST_AIML": """
ROLE: Analytics, Data Science & Applied AI/ML
EVALUATION RUBRIC:
- Work Experience (0-20):
  * Tier-1 (18-20 pts): Top Analytics & Applied AI firms (American Express, J.P. Morgan Chase, Zepto Data Science, Info Edge, Capital One, EXL, Fractal Analytics, Mastercard, Visa).
  * Tier-2 (14-17 pts): Data analyst / BI / ML intern roles at high-growth startups or corporate fintech.
  * Tier-3 (10-13 pts): General software or basic data entry / dashboarding.
- Projects & ML Depth (0-20):
  * End-to-end ML pipelines, deep learning research, statistical A/B testing, NLP, computer vision, production model deployments, Kaggle competitions.
- SCOPE Articulation (0-20):
  * Strong action verbs + exact statistical/ML metrics (Accuracy, ROC-AUC, F1, RMSE, latency, inference speedup, business conversion %).
""",
    "QUANT": """
ROLE: Quantitative Finance (HFT / Quantitative Research / Trading / Development)
EVALUATION RUBRIC:
- Work Experience (0-20):
  * Tier-1 (18-20 pts): Prop trading / HFT desks (Quadeye, Graviton, Tower, AlphaGrep, Carlsen, D.E. Shaw, WorldQuant, Squarepoint, NK Securities) OR Core Systems/Low-Latency Engineering at Tier-1 tech (Google Systems, Databricks, Rubrik, Uber Infra).
  * Tier-2 (14-17 pts): Core backend/HPC/distributed algorithms at top tech/fintech (Swiggy, Flipkart, Razorpay, Sprinklr).
- Projects & Technical Depth (0-20):
  * Low-level systems (C++ custom malloc, page tables, GemOS kernel, lock-free queues, TCP raw sockets, Z3 SMT solvers) OR mathematical modeling (stochastic calculus, Monte Carlo, statistical arbitrage).
- SCOPE Articulation (0-20):
  * Strong action verbs + technical precision + quantified performance proof (latency in ns/µs, throughput, Sharpe ratio, speedup %).
""",
    "SDE": """
ROLE: Software Development Engineering (SDE / SWE / Systems / Full-Stack)
TARGET FIRMS: Tier-1 Tech MNCs, High-Growth Unicorns, & Core Systems (Google, Microsoft, Amazon, Databricks, Rubrik, Uber, Atlassian, Flipkart, Sprinklr, Swiggy, Zepto, Razorpay, Cred, Goldman Sachs Core Engg, Qualcomm, NVIDIA).

EVALUATION FRAMEWORK:
1. Work Experience & Research Pedigree (0-20):
   * Outstanding (18-20 pts): SWE internship at Tier-1 Tech (Google, Microsoft, Amazon, Databricks, Rubrik, Uber, Atlassian, Sprinklr) OR high-impact backend/systems role at top tech unicorns (Swiggy, Zepto, Razorpay). OR Systems/Compilers/Security research at Top Global Universities (MIT, Stanford, CMU, Oxford, Berkeley, ETH Zurich, MSR, Google Research).
   * Very Good (14-17 pts): Software Engineering internship at established tech firms, Series A+ startups, or SURGE at IITK in systems/networking under CSE faculty.
   * Good (10-13 pts): General software development, QA/SDET, or full-stack engineering trainee experience.
   * Diluting (<10 pts): Non-technical roles (marketing, operations) or basic data entry.

2. Projects & Systems Depth (0-20):
   * Baseline Expectation: Must have at least ONE code-driven project (Full-Stack, ML pipeline, backend API, systems, CLI tool). Resumes with zero code projects face severe penalty.
   * Scalable Backend & Distributed Systems (18-20 pts): Microservices, gRPC/REST APIs, asynchronous task queues (Kafka, RabbitMQ), caching (Redis), database sharding/indexing, rate limiting, Docker/k8s container orchestration.
   * Low-Level Systems & Networks (18-20 pts): Multi-threaded C++/Rust servers, custom malloc, lock-free queues, storage engine (LSM/B-Tree), compilers, or OS kernel modules (GemOS/xv6).
   * Production Full-Stack (14-17 pts): End-to-end applications (React/Next + Go/Node/Python + PostgreSQL), OAuth/JWT, CI/CD, and live deployment with real users.
   * Open-Source Spikes: GSoC contributor/mentor, merged PRs in major OSS repos, actively starred GitHub projects.

3. SCOPE Articulation & Systems Precision (0-20):
   * Strong Action Verbs + Architectural Clarity + Quantified Engineering Proof: Latency reduction (ms/µs), QPS / throughput scaling, concurrent user load, memory footprint reduction, test coverage %.
   * Red Flags to Penalize: Static UI tutorial clones without backend logic (Netflix/Spotify HTML/CSS clones), 15-language shopping lists in skills, or vague descriptions without metrics.
""",
    "CONSULT_PM": """
ROLE: Management Consulting & Product Management (Strategy, General Management)
EVALUATION RUBRIC:
- Work Experience (0-20):
  * Tier-1 (18-20 pts): MBB (McKinsey, BCG, Bain), Tier-1 Strategy (Kearney, Strategy&, Alvarez & Marsal, Oliver Wyman), Elite Conglomerates (Aditya Birla Group - ABG, TAS, HUL, ITC), or APM roles at top tech (Google, Uber, Swiggy).
  * Tier-2 (14-17 pts): Big-4 Strategy, high-growth startup operations/strategy, boutique consulting.
  * Tier-3 (10-13 pts): General business development, marketing, sales.
- Projects & Initiatives (0-20):
  * High-impact business cases, consulting club projects (Consoc/180DC), product teardowns, revenue/cost optimization.
- SCOPE Articulation (0-20):
  * Clear business impact ($ saved, % margin expansion, revenue growth, stakeholder management).
""",
    "CORE_TECHNOM": """
ROLE: Core Engineering & Techno-Managerial (TechnoM / Supply Chain / Operations / Field Engineering)
TARGET FIRMS: Top Core MNCs, Manufacturing Conglomerates, Energy Giants, & FMCG Supply Chain (SLB/Schlumberger, HUL Supply Chain ULIP, Nestlé Operations, ITC Technical Management, Shell, ExxonMobil, Tata Steel, Bajaj Auto, Maruti Suzuki, Texas Instruments, Qualcomm, General Electric, Baker Hughes, Reliance, L&T, Cairn).

EVALUATION FRAMEWORK:
1. Work Experience (0-20):
   * Outstanding (18-20 pts): On-site plant/refinery/manufacturing/field engineering internship at major industrial conglomerates (Tata Steel, Reliance, SLB, Shell, HUL Plants, ITC, Bajaj Auto, Maruti, Bosch, TI, GE, Aditya Birla Group) with shop-floor ownership (throughput increase, cycle time reduction, scrap/contamination reduction, equipment reliability).
   * Very Good (14-17 pts): Technical engineering or operations internship at mid-scale manufacturing firms, automotive tier-1 suppliers, or industrial/hardware startups.
   * Good (10-13 pts): General operations, logistics, or engineering trainee experience.
   * Diluting (<10 pts): Generic frontend/web dev CRUD apps, basic data entry, or non-technical marketing/sales roles.

2. Core Projects, Technical Teams & Research Pedigree (0-20):
   * Professor-Guided Projects: BTP, UGP, SURGE at IITK, or research internships with faculty from IITs/top global universities (MITACS, DAAD WISE, BARC, ISRO, DRDO, IISc) with physical/simulation rigor (FEA, CFD, CAD/CAE, ANSYS, COMSOL, SolidWorks, MATLAB/Simulink, material characterization XRD/SEM/TEM).
   * Project Mentorship as Valid Substitute: Serving as a Project Mentor guiding junior batches in SnT Council / technical clubs / departmental projects strongly validates both technical depth and leadership.
   * Student Technical Teams (Spike): SAE IITK (BAJA / Formula Student), Team Robocon, Team Aeromodelling, AUV IITK.

3. Relevant Coursework & Operational SCOPE Rigor (0-20):
   * Coursework Check: Must highlight foundational engineering courses (Thermodynamics, Fluid Mechanics, Heat & Mass Transfer, Manufacturing Processes, Mechanics of Solids, Material Characterization, Control Systems, Phase Equilibria, Transport Phenomena). Flag if omitted!
   * Operational SCOPE Metrics: Equipment scale, operating temperatures/pressures, manufacturing volume, plant capacity, cycle time reduction, efficiency %, cost savings (e.g. ₹L+), or quality improvements.
"""
}


# ============================================================
# 2. DETERMINISTIC HARD SIGNALS EXTRACTION
# ============================================================

def extract_deterministic_signals(resume_json: Dict[str, Any], raw_text: str, track: str) -> Tuple[Dict[str, Any], Dict[str, int]]:
    signals = {}

    # 1. Department / Branch (Prioritize based on target track)
    dept_raw = resume_json.get("Department", "") or ""
    branches = {
        "CSE": ["Computer Science", "CSE", "Computer Science and Engineering"],
        "EE": ["Electrical Engineering", "EE"],
        "MTH": ["Mathematics and Scientific Computing", "Mathematics", "MTH", "MnC"],
        "SDS": ["Statistics and Data Science", "SDS", "Statistics"],
        "ME": ["Mechanical", "ME"],
        "CHE": ["Chemical", "CHE"],
        "MSE": ["Materials Science", "Materials Science and Engineering", "MSE"],
        "CE": ["Civil Engineering", "CE"],
        "AE": ["Aerospace Engineering", "AE"],
        "BSBE": ["Biological Sciences", "BSBE"],
        "ECO": ["Economics", "ECO"]
    }
    
    if track == "CORE_TECHNOM":
        priority_order = ["EE", "ME", "CHE", "MSE", "AE", "CE", "CSE", "MTH", "SDS", "BSBE", "ECO"]
    else:
        priority_order = ["CSE", "MTH", "SDS", "EE", "ME", "CHE", "MSE", "AE", "CE", "BSBE", "ECO"]

    def _match_branch(text: str) -> str:
        """First code in track-priority order whose alias appears in `text`."""
        for b_code in priority_order:
            for alias in branches.get(b_code, []):
                if re.search(r"\b" + re.escape(alias) + r"\b", text, re.IGNORECASE):
                    return b_code
        return "OTHER"

    # The Department field is authoritative and is resolved on its own first.
    #
    # Previously the field and the first 1200 characters of raw text were concatenated and
    # scanned together, so any incidental mention outranked the real department whenever it
    # belonged to a code earlier in `priority_order`. "Indian Olympiad Qualifier in
    # Mathematics" in a scholastic line was enough to classify an Electrical Engineering
    # candidate as MTH — which inflates SDE by 2 points and costs CORE_TECHNOM 15, because
    # EE scores 20 there and MTH scores 5.
    #
    # Priority order still decides genuine ambiguity, such as a dual degree naming two
    # departments in the same field. Raw text remains the fallback when the field is
    # missing or unrecognised, which is what it was there for.
    detected_branch = _match_branch(dept_raw) if dept_raw.strip() else "OTHER"
    branch_source = "department_field"
    if detected_branch == "OTHER":
        detected_branch = _match_branch(raw_text[:1200])
        branch_source = "raw_text_fallback" if detected_branch != "OTHER" else "undetected"

    signals["branch"] = detected_branch
    # Recorded so the validation agent can flag a branch inferred from prose rather than
    # read from the field.
    signals["branch_source"] = branch_source

    # 2. Field-Scoped CPI Extraction (Strictly from B.Tech/IITK qualifications row)
    cpi = None
    for acad in resume_json.get("Academic Qualifications", []):
        deg = (acad.get("degree") or "").lower()
        inst = (acad.get("institution") or "").lower()
        grade_str = acad.get("grade") or ""
        
        # Must be college / B.Tech row (not Class XII/X %)
        if "b.tech" in deg or "bs" in deg or "dual" in deg or "iit" in inst or "indian institute" in inst or "present" in (acad.get("year") or "").lower():
            m = re.search(r"\b([5-9]\.\d{1,2}|10(?:\.0{1,2})?)", grade_str)
            if m:
                cpi = float(m.group(1))
                break

    if cpi is None:
        # Strict fallback only on explicit CPI/CGPA keywords
        m = re.search(r"\b(?:CPI|CGPA)\s*[:=]?\s*([5-9]\.\d{1,2}|10(?:\.0{1,2})?)", raw_text, re.IGNORECASE)
        cpi = float(m.group(1)) if m else None

    signals["cpi"] = cpi
    signals["cpi_status"] = "VERIFIED" if cpi is not None else "UNVERIFIED_MISSING"

    # 3. JEE Advanced AIR Rank
    jee_adv = re.search(r"(?:All\s*India\s*Rank|AIR)\s*(\d{1,4})\s*(?:in\s*JEE\s*Advanced)", raw_text, re.IGNORECASE)
    if not jee_adv:
        jee_adv = re.search(r"JEE\s*Advanced\s*(?:20\d\d)?\s*[:\-]?\s*(?:AIR\s*)?(\d{1,4})", raw_text, re.IGNORECASE)
    signals["jee_adv_air"] = int(jee_adv.group(1)) if jee_adv else None

    # 4. Codeforces / CP Rating (Strictly requiring coding platform context)
    cf_pattern = r"(?:Codeforces|CF|CodeChef|LeetCode|AtCoder)\b[^\.\n]{0,35}\b(?:rating|max\s*rating|rank)?\s*[:=]?\s*(\d{3,4})|(\d{3,4})\s*\((?:Candidate\s*Master|International\s*Master|Master|Expert|Grandmaster)\)"
    cf_match = re.search(cf_pattern, raw_text, re.IGNORECASE)
    if cf_match:
        vals = [g for g in cf_match.groups() if g]
        signals["cf_rating"] = int(vals[0]) if vals else None
    else:
        signals["cf_rating"] = None

    # 5. Institutional Spikes & Scholarships (scoped strictly to Scholastic Qualifications)
    scholastics_str = " ".join(resume_json.get("Scholastic Qualifications", [])) + " " + " ".join(resume_json.get("Scholastic Achievements", [])) + " " + raw_text
    signals["has_top_scholarship"] = bool(re.search(r"\b(Quadeye\s*Excellence|AlphaGrep\s*Scholarship|OPJEMS|Aditya\s*Birla\s*(?:Group\s*)?Scholarship|O\.P\.\s*Jindal|Class\s*of\s*1990\s*Scholarship|Optiver\s*Future\s*Focus)\b", scholastics_str, re.IGNORECASE))
    signals["has_olympiad"] = bool(re.search(r"\b(INPhO|INMO|IChO|INAO|INChO|IOQP|NSEA|OCSC|International\s*Olympiad|National\s*Olympiad)\b", scholastics_str, re.IGNORECASE))
    signals["has_aea"] = bool(re.search(r"\b(Academic\s*Excellence\s*Award|AEA)\b", scholastics_str, re.IGNORECASE))
    signals["has_kvpy"] = bool(re.search(r"\bKVPY\b", scholastics_str, re.IGNORECASE))
    signals["has_surge"] = bool(re.search(r"\b(SURGE|MITACS|DAAD\s*WISE)\b", raw_text, re.IGNORECASE))

    # 6. Gymkhana 7-Tier PoR (Scoped strictly to Position of Responsibility section)
    por_entries = resume_json.get("Position of Responsibility", [])
    pors_str = " ".join([p.get("position", "") + " " + p.get("organization", "") for p in por_entries])
    
    por_tier = 8
    if por_entries:
        if re.search(r"\b(President,?\s*Students'?\s*Gymkhana|PSG|Chairperson,?\s*Students'?\s*Senate|General\s*Secretary|GenSec|OPC|ISEC)\b", pors_str, re.IGNORECASE):
            por_tier = 1
        elif re.search(r"\b(Core\s*Team\s*Member|CTM|APC|COSHA|Parliamentarian)\b", pors_str, re.IGNORECASE):
            por_tier = 2
        elif re.search(r"\b(Co-?ordinator|Manager)\b", pors_str, re.IGNORECASE) and re.search(r"\b(Institute\s*Counselling\s*Group|ICG|4th\s*Year\s*PoR)\b", pors_str, re.IGNORECASE):
            por_tier = 3
        elif re.search(r"\b(Manager,?\s*Share\s*IITK|Manager,?\s*Share)\b", pors_str, re.IGNORECASE):
            por_tier = 5
        elif re.search(r"\b(Co-?ordinator|Assistant\s*Co-?ordinator|Leader|Head|Convener)\b", pors_str, re.IGNORECASE):
            por_tier = 4
        elif re.search(r"\b(Executive|Team\s*Lead)\b", pors_str, re.IGNORECASE):
            por_tier = 6
        elif re.search(r"\b(Secretary|Secy|Joint\s*Secretary)\b", pors_str, re.IGNORECASE):
            por_tier = 7
    signals["por_tier"] = por_tier

    # 7. Known Recruiter Companies (Scoped strictly to Work Experience section)
    work_ex_str = " ".join([w.get("organization", "") + " " + w.get("role", "") for w in resume_json.get("Work Experience", [])])
    known_analyst_firms = ["American Express", "Amex", "J.P. Morgan", "JPMorgan", "Zepto", "Info Edge", "Capital One", "EXL", "Fractal", "Mastercard", "Visa", "Goldman Sachs"]
    signals["detected_analyst_firms"] = [f for f in known_analyst_firms if re.search(r"\b" + re.escape(f) + r"\b", work_ex_str, re.IGNORECASE)]

    # 7b. Recruiter knowledge graph resolution — ADDITIVE ONLY.
    #
    # `detected_analyst_firms` above is left exactly as originally written, because the
    # extracted signal corpora were produced against that behaviour and its values must
    # stay comparable. The KG lookup is published under separate keys instead, so the
    # validation agent can flag an organisation the graph has never seen (brief §3.1)
    # without changing any value the scorer already emitted.
    #
    # The KG's own edge distinction is preserved: `pedigree_for` means an internship there
    # is a positive signal when scoring past experience — never a claim that the candidate
    # could receive an offer there.
    kg_pedigree, kg_unverified = [], []
    for entry in resume_json.get("Work Experience", []) or []:
        org = (entry.get("organization") or "").split(",")[0].strip()
        if not org:
            continue
        info = _kg_pedigree(org, track)
        if info is None:
            kg_unverified.append(org)
        else:
            kg_pedigree.append({
                "organization": org,
                "resolved_as": info.display_name,
                "tier": info.tier,
                # The tier word and the rubric point band it corresponds to. This block is
                # serialised into the qualitative evaluator's HARD SIGNALS context, so the
                # model can bind a resolved company to the rubric band directly instead of
                # guessing what a bare integer means. The tier is role-specific: Texas
                # Instruments is Tier-2 for SDE and Tier-1 for CORE_TECHNOM.
                "tier_label": info.tier_label,
                "rubric_band_points": info.rubric_band,
                "category": info.category,
                "edge_type": info.edge_type,
                "recruiting_mode": info.recruiting_mode,
            })
    signals["kg_pedigree_firms"] = kg_pedigree
    signals["kg_unverified_firms"] = kg_unverified

    # 7c. Quantified results — ADDITIVE ONLY.
    #
    # The numbers a candidate reports are what turn "described the work" into "showed
    # what the work achieved", so they are extracted deterministically and published in
    # the same {metric, direction, value, unit} shape the signal corpora use. Because
    # `signals` is serialised into the qualitative evaluator's HARD SIGNALS block, the
    # evaluator sees exactly which figures the resume actually reports when it scores
    # SCOPE articulation and work-experience impact — grounded rather than impressionistic.
    #
    # Nothing here changes a score directly, and every entry carries its source bullet so
    # the validation layer can trace it back to the PDF.
    # 7d. Scholastic achievements — ADDITIVE ONLY.
    #
    # `has_olympiad` and friends above are booleans, so a state screening exam and an
    # international medal were indistinguishable, and IOQM, NSEP, NSEC, state entrances,
    # NEET and admission offers were not detected at all. This tiers each achievement
    # against the role frameworks' own bands and carries the basis for every call, so a
    # reviewer can check it. The original booleans are untouched.
    scholastic = _scholastic(resume_json, raw_text)
    if scholastic is not None:
        signals["scholastic_signals"] = scholastic["signals"]
        signals["scholastic_summary"] = {
            "total": scholastic["total"],
            "by_tier": scholastic["by_tier"],
            "strongest_tier": scholastic["strongest_tier"],
            "olympiad_stage": scholastic["olympiad_stage"],
            "diluting_count": len(scholastic["diluting"]),
        }

    impact = _quantified_impact(resume_json)
    if impact is not None:
        signals["quantified_results"] = impact["results"]
        signals["quantified_results_summary"] = {
            "total": impact["total"],
            "by_section": impact["by_section"],
            "quantified_bullets": impact["quantified_bullets"],
            "total_bullets": impact["total_bullets"],
            "quantified_bullet_ratio": impact["quantified_bullet_ratio"],
            "named_metrics": impact["named_metrics"],
        }

    # 8. Deterministic Pillar Scoring
    det_scores = {}

    # Academics (0-20): Strict Policy (Missing CPI receives unverified baseline 4/20; cannot outperform disclosed CPI)
    if cpi is None:
        acad_score = 4
    elif track == "QUANT":
        acad_score = 20 if cpi >= 9.5 else (18 if cpi >= 9.0 else (13 if cpi >= 8.5 else (8 if cpi >= 8.0 else 4)))
    elif track == "CORE_TECHNOM":
        acad_score = 20 if cpi >= 8.5 else (17 if cpi >= 8.0 else (14 if cpi >= 7.5 else (10 if cpi >= 6.5 else 4)))
    elif track == "SDE":
        acad_score = 20 if cpi >= 9.0 else (18 if cpi >= 8.5 else (16 if cpi >= 8.0 else (14 if cpi >= 7.5 else (10 if cpi >= 6.5 else 4))))
    else:
        acad_score = 20 if cpi >= 9.0 else (17 if cpi >= 8.5 else (14 if cpi >= 8.0 else (11 if cpi >= 7.5 else (8 if cpi >= 7.0 else (6 if cpi >= 6.5 else 4)))))

    # Competitive programming bonus only for Tech / Quant / Analyst
    if signals.get("cf_rating") and track in ["SDE", "QUANT", "ANALYST_AIML"]:
        cfr = signals["cf_rating"]
        if cfr >= 2000:
            acad_score = min(20, acad_score + 4)
        elif cfr >= 1800:
            acad_score = min(20, acad_score + 3)
        elif cfr >= 1600:
            acad_score = min(20, acad_score + 2)

    if signals.get("jee_adv_air"):
        if signals["jee_adv_air"] <= 200:
            acad_score = min(20, acad_score + 3)
        elif signals["jee_adv_air"] <= 500:
            acad_score = min(20, acad_score + 2)

    if signals.get("has_top_scholarship"):
        acad_score = min(20, acad_score + 3)
    if signals.get("has_olympiad"):
        acad_score = min(20, acad_score + 2)
    if signals.get("has_aea"):
        acad_score = min(20, acad_score + 2)
    if signals.get("has_kvpy"):
        acad_score = min(20, acad_score + 1)
    if signals.get("has_surge") and track in ["CORE_TECHNOM", "SDE"]:
        acad_score = min(20, acad_score + 2)

    det_scores["Academics"] = min(20, acad_score)

    # Branch Match (0-20)
    if track == "CORE_TECHNOM":
        det_scores["Branch"] = {"EE": 20, "ME": 18, "CHE": 16, "MSE": 14, "AE": 15, "CE": 12}.get(detected_branch, 5)
    elif track in ["SDE", "ANALYST_AIML", "QUANT"]:
        det_scores["Branch"] = {"CSE": 20, "MTH": 20, "SDS": 20, "EE": 18}.get(detected_branch, 12 if track == "ANALYST_AIML" else 10)
    elif track == "CONSULT_PM":
        det_scores["Branch"] = 16
    else:
        det_scores["Branch"] = 14

    # Leadership / PoR (0-20) with strict monotonic hierarchy (Tier 5 Manager Share IITK reachable, No PoR = 4/20)
    if track in ["CONSULT_PM", "CORE_TECHNOM"]:
        det_scores["Leadership"] = {1: 20, 2: 18, 3: 15, 4: 13, 5: 11, 6: 8, 7: 6, 8: 3}[por_tier]
    else:
        det_scores["Leadership"] = {1: 20, 2: 18, 3: 16, 4: 14, 5: 12, 6: 10, 7: 8, 8: 4}[por_tier]

    return signals, det_scores


def evaluate_core_coursework(resume_json: Dict[str, Any], raw_text: str) -> Tuple[int, str, str]:
    """Explicitly evaluates foundational core engineering coursework for CORE_TECHNOM."""
    courses = resume_json.get("Relevant Courses", [])
    courses_str = " ".join(courses) + " " + raw_text
    core_keywords = [
        "Thermodynamics", "Heat Transfer", "Mass Transfer", "Fluid Mechanics",
        "Rate Processes", "Mechanics of Solids", "Manufacturing", "Material Characterization",
        "Phase Equilibria", "Control Systems", "Machine Design", "Transport Phenomena"
    ]
    matched = [k for k in core_keywords if re.search(r"\b" + re.escape(k) + r"\b", courses_str, re.IGNORECASE)]
    
    if len(matched) >= 3:
        score = 18
        tier = "Outstanding"
        reasoning = f"Comprehensive foundational core engineering coursework listed ({len(matched)} core subjects: {', '.join(matched[:3])})."
    elif len(matched) >= 1:
        score = 14
        tier = "Good"
        reasoning = f"Contains core coursework exposure ({', '.join(matched)}), but could add further advanced departmental electives."
    else:
        score = 6
        tier = "Below Par"
        reasoning = "Omits foundational core engineering courses (e.g. Thermodynamics, Rate Processes, Manufacturing)."
    
    return score, tier, reasoning


# ============================================================
# 3. STRICT SEMANTIC VALIDATOR & GEMINI QUALITATIVE SAFETY-NET
# ============================================================

def _sanitize_score(val: Any) -> int:
    if val is None:
        return 10
    try:
        return min(20, max(0, int(round(float(str(val).strip())))))
    except (ValueError, TypeError):
        return 10

def _sanitize_tier(tier_val: Any, score: int) -> str:
    valid_tiers = ["Outstanding", "Very Good", "Good", "Below Par", "Weak"]
    t_str = str(tier_val).strip().title()
    if t_str in valid_tiers:
        return t_str
    if score >= 18:
        return "Outstanding"
    elif score >= 14:
        return "Very Good"
    elif score >= 10:
        return "Good"
    elif score >= 6:
        return "Below Par"
    return "Weak"

def _validate_and_sanitize_semantic_data(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError(f"Semantic evaluation output must be a JSON dictionary, received: {type(data)}")

    we_score = _sanitize_score(data.get("work_experience_score"))
    pj_score = _sanitize_score(data.get("projects_score"))
    sc_score = _sanitize_score(data.get("scope_articulation_score"))

    return {
        "work_experience_score": we_score,
        "work_experience_tier": _sanitize_tier(data.get("work_experience_tier"), we_score),
        "work_experience_reasoning": str(data.get("work_experience_reasoning") or "Evaluated against track rubric.").strip(),
        "projects_score": pj_score,
        "projects_tier": _sanitize_tier(data.get("projects_tier"), pj_score),
        "projects_reasoning": str(data.get("projects_reasoning") or "Evaluated against track rubric.").strip(),
        "scope_articulation_score": sc_score,
        "scope_articulation_tier": _sanitize_tier(data.get("scope_articulation_tier"), sc_score),
        "scope_articulation_reasoning": str(data.get("scope_articulation_reasoning") or "Evaluated against track rubric.").strip()
    }


def _corpus_corroboration(corpus_match: Optional[Dict[str, Any]], track: str) -> str:
    """
    The keyword baseline's findings, as corroboration for the qualitative read.

    The baseline and the evaluator previously scored the same pillars from the same
    resume without ever seeing each other, so they diverged for reasons neither could
    explain — usually vocabulary rather than substance. Handing the evaluator the matched
    anchors closes that gap from the side that has evidence behind it.

    Deliberately passes the anchor LABELS and counts, never the baseline's scores and
    never a corpus `evidence` string. Two reasons: a score would be anchored to, and the
    baseline reaches only a fraction of each corpus so its zeros are usually misses, not
    findings; and the evidence strings are verbatim material from real candidates'
    resumes, which must not travel into another candidate's evaluation.
    """
    if not corpus_match:
        return ""
    anchors = [a for a in (corpus_match.get("sample_matched_corpus_anchors") or []) if a]
    proj_n = corpus_match.get("matched_proj_anchors_count") or 0
    work_n = corpus_match.get("matched_work_anchors_count") or 0

    # Only the baseline's positive findings are sent, and the block is omitted entirely
    # when it found nothing.
    #
    # An earlier version reported "0 anchors matched" with an instruction to treat it as
    # no information. Measured against the same resume, the evaluator lowered projects
    # 14 -> 12 and SCOPE 10 -> 8 anyway: a zero in the prompt gets anchored to whatever
    # the surrounding words say. Since the baseline reaches roughly a sixth of each
    # corpus, those zeros are mostly vocabulary it does not know — so the honest thing
    # is to say nothing rather than to say nothing was found.
    if not anchors and not proj_n and not work_n:
        return ""

    lines = [
        f"CORPUS BENCHMARK MATCHES ({track} corpus of "
        f"{corpus_match.get('total_role_signals', 0)} signals from resumes that placed "
        "well in this track):",
    ]
    if proj_n:
        lines.append(f"  project anchors matched: {proj_n}")
    if work_n:
        lines.append(f"  work-experience anchors matched: {work_n}")
    if anchors:
        lines.append("  matched anchors: " + ", ".join(str(a) for a in anchors[:6]))
    return "\n".join(lines) + "\n\n"


def evaluate_semantic_with_safety_net(
    resume_json: Dict[str, Any],
    raw_text: str,
    hard_signals: Dict[str, Any],
    track: str,
    api_key: str,
    model_name: str = "gemini-3.6-flash",
    corpus_match: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    rubric = ROLE_RUBRICS.get(track, ROLE_RUBRICS["ANALYST_AIML"])

    system_prompt = (
        f"You are an expert IIT Kanpur Placement Evaluator assessing a resume for the target track: '{track}'.\n"
        f"Evaluate the resume against this track-specific rubric:\n\n{rubric}\n\n"
        "Instructions:\n"
        "1. Provide qualitative scores (integer 0-20) strictly adhering to the tier definitions above.\n"
        "2. Ground each tier in verifiable facts from the candidate's projects, internships, and quantified achievements.\n"
        "3. Every score MUST be an integer between 0 and 20.\n"
        "4. If CORPUS BENCHMARK MATCHES appears, each anchor is independent corroboration "
        "from resumes that previously placed well in this track — name it in your reasoning "
        "and let it support the tier. The section only ever lists what was found, so it can "
        "raise your confidence but never lower it; if it is absent, judge the resume text "
        "alone.\n"
        # Appended, not substituted: the rubric above still leads and owns the bands.
        + _role_framework(track)
    )

    prompt = (
        "STRUCTURED RESUME DATA:\n"
        + json.dumps(resume_json, indent=2) + "\n\n"
        + "HARD SIGNALS:\n"
        + json.dumps(hard_signals, indent=2) + "\n\n"
        + _corpus_corroboration(corpus_match, track)
        + "RAW RESUME TEXT:\n"
        + raw_text + "\n\n"
        + "Return a valid JSON object strictly conforming to this structure:\n"
        + "{\n"
        + '  "work_experience_score": (int 0-20),\n'
        + '  "work_experience_tier": ("Outstanding" | "Very Good" | "Good" | "Below Par" | "Weak"),\n'
        + '  "work_experience_reasoning": (string: 1 clear sentence),\n'
        + '  "projects_score": (int 0-20),\n'
        + '  "projects_tier": ("Outstanding" | "Very Good" | "Good" | "Below Par" | "Weak"),\n'
        + '  "projects_reasoning": (string: 1 clear sentence),\n'
        + '  "scope_articulation_score": (int 0-20),\n'
        + '  "scope_articulation_tier": ("Outstanding" | "Very Good" | "Good" | "Below Par" | "Weak"),\n'
        + '  "scope_articulation_reasoning": (string: 1 clear sentence)\n'
        + "}\n"
    )

    try:
        # Shared transport: same prompt, same JSON mode, same parsing — but routed
        # through the model chain so a "high demand" 503 on one model steps to the
        # next instead of failing the whole evaluation. Falls back to the direct
        # client if the app layer is not importable (CLI use from scoring/ alone).
        shared = _shared_transport()
        if shared is not None:
            raw_data = json.loads(shared(
                prompt=prompt,
                config={
                    "system_instruction": system_prompt,
                    "response_mime_type": "application/json"
                },
                api_key=api_key,
                stage=f"semantic:{track}",
            ))
        elif HAS_NEW_GENAI:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={
                    "system_instruction": system_prompt,
                    "response_mime_type": "application/json"
                }
            )
            raw_data = json.loads(response.text)
        else:
            legacy_genai.configure(api_key=api_key)
            model = legacy_genai.GenerativeModel(
                model_name=model_name,
                system_instruction=system_prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            response = model.generate_content(prompt)
            raw_data = json.loads(response.text)
            
        return _validate_and_sanitize_semantic_data(raw_data)
    except Exception as e:
        # Strict failure: do not fabricate high scores when semantic evaluation fails
        raise RuntimeError(f"Qualitative semantic evaluation failed for track '{track}': {e}")


# ============================================================
# ROLE-SPECIFIC PILLAR WEIGHTS
# ============================================================

ROLE_WEIGHTS = {
    "ANALYST_AIML": {
        "Work Experience": 0.25,
        "Projects & Depth": 0.25,
        "Academics & CPI": 0.20,
        "SCOPE Articulation": 0.15,
        "Branch Match": 0.10,
        "Leadership & PoR": 0.05
    },
    "QUANT": {
        "Academics & CPI": 0.35,
        "Projects & Depth": 0.25,
        "Work Experience": 0.20,
        "Branch Match": 0.10,
        "SCOPE Articulation": 0.05,
        "Leadership & PoR": 0.05
    },
    "CONSULT_PM": {
        "Leadership & PoR": 0.25,
        "Work Experience": 0.25,
        "Projects & Depth": 0.20,
        "Academics & CPI": 0.15,
        "SCOPE Articulation": 0.10,
        "Branch Match": 0.05
    },
    "CORE_TECHNOM": {
        "Work Experience": 0.25,
        "Projects & Depth": 0.20,
        "Leadership & PoR": 0.20,
        "Branch Match": 0.15,
        "Coursework & SCOPE": 0.10,
        "Academics & CPI": 0.10
    },
    "SDE": {
        "Work Experience": 0.25,
        "Projects & Depth": 0.20,
        "Academics & CPI": 0.20,
        "Branch Match": 0.15,
        "SCOPE Articulation": 0.10,
        "Leadership & PoR": 0.10
    }
}


# ============================================================
# 4. MASTER SCORING PIPELINE
# ============================================================

def score_resume(
    pdf_path: str,
    track: str = "ANALYST_AIML",
    api_key: Optional[str] = None,
    model_name: str = "gemini-3.6-flash"
) -> Dict[str, Any]:
    if track not in ROLE_WEIGHTS:
        raise ValueError(f"Invalid track '{track}'. Must be one of: {list(ROLE_WEIGHTS.keys())}")

    key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY is required.")

    # 1. Structure & Layout Evaluation (Module Structure)
    struct_parser = RelaxedResumeParser(pdf_path)
    # Track is passed through so the visual reading compares against the right
    # convention; `composite_score` equals the geometric score whenever no visual
    # backend ran, so the default path is unchanged.
    struct_eval = struct_parser.eval_all(track=track)
    structural_score = struct_eval.get("composite_score", struct_eval["score"])
    spo_metrics = struct_eval["metrics"]

    # 2. High-Fidelity Table Extraction (PyMuPDF) -> Structured Resume JSON (Module A)
    raw_markdown = extract_pdf_markdown(pdf_path)
    resume_json = markdown_to_resume_json(raw_markdown, api_key=key, model_name=model_name)

    # 3. Extract Deterministic Hard Signals
    signals, det_scores = extract_deterministic_signals(resume_json, raw_markdown, track)

    # 4. Positive Signal Semantic Similarity Matching against Track Benchmark Corpus
    semantic_match = match_candidate_against_signal_corpus(resume_json, raw_markdown, track)

    # 4. Gemini Qualitative Safety Net Evaluation
    sem_eval = evaluate_semantic_with_safety_net(
        resume_json=resume_json,
        raw_text=raw_markdown,
        hard_signals=signals,
        track=track,
        api_key=key,
        model_name=model_name,
        # The corpus match was previously computed and never shown to the evaluator, so
        # the two scored the same pillars in ignorance of each other.
        corpus_match=semantic_match,
    )

    # 4b. Evidence floors — deterministic minimums for the two pillars where the KG and
    # the quantified-impact extractor carry direct evidence.
    #
    # ROLE_RUBRICS already states what the evidence is worth ("Tier-1 (18-20 pts)"), so
    # when the knowledge graph independently confirms a firm is Tier-1 for this role, an
    # 18 floor enforces the rubric rather than overriding it. Floors NEVER lower a score
    # and sit at the bottom of the band, so the qualitative evaluator remains free to
    # score higher. Every application is recorded in `evidence_adjustments`.
    #
    # Applied before pillar assembly so CORE_TECHNOM's blended Coursework & SCOPE uses
    # the floored value.
    floored_we, floored_scope, floored_acad, evidence_adjustments = _evidence_floors(
        sem_eval["work_experience_score"], sem_eval["scope_articulation_score"], signals,
        academics_score=det_scores.get("Academics"), track=track,
    )
    if floored_acad is not None and floored_acad != det_scores.get("Academics"):
        det_scores["Academics"] = floored_acad
    if floored_we != sem_eval["work_experience_score"]:
        sem_eval["work_experience_score"] = floored_we
        sem_eval["work_experience_tier"] = _sanitize_tier(None, floored_we)
    if floored_scope != sem_eval["scope_articulation_score"]:
        sem_eval["scope_articulation_score"] = floored_scope
        sem_eval["scope_articulation_tier"] = _sanitize_tier(None, floored_scope)

    # 5. Dynamic Project Pillar Label per Track
    project_label_map = {
        "ANALYST_AIML": "Projects & ML Depth",
        "QUANT": "Projects & Technical/Math Depth",
        "CONSULT_PM": "Projects & Strategic Initiatives",
        "CORE_TECHNOM": "Core Projects & Research Pedigree",
        "SDE": "Projects & Systems Depth"
    }
    proj_label = project_label_map.get(track, "Projects & ML Depth")

    # 6. Assemble Content Pillars
    if track == "CORE_TECHNOM":
        cw_score, cw_tier, cw_reason = evaluate_core_coursework(resume_json, raw_markdown)
        # Combined Coursework & Operational SCOPE (10% weight)
        scope_score = round(0.5 * cw_score + 0.5 * sem_eval["scope_articulation_score"])
        pillars = {
            "Work Experience": {
                "score": sem_eval["work_experience_score"],
                "tier": sem_eval["work_experience_tier"],
                "reasoning": sem_eval["work_experience_reasoning"]
            },
            proj_label: {
                "score": sem_eval["projects_score"],
                "tier": sem_eval["projects_tier"],
                "reasoning": sem_eval["projects_reasoning"]
            },
            "Leadership & PoR": {
                "score": det_scores["Leadership"],
                "tier": "Outstanding" if det_scores["Leadership"] >= 18 else ("Very Good" if det_scores["Leadership"] >= 14 else "Good")
            },
            "Branch Match": {
                "score": det_scores["Branch"],
                "tier": "Tier 1-2 Core" if det_scores["Branch"] >= 18 else ("Tier 3-4 Core" if det_scores["Branch"] >= 14 else "Neutral")
            },
            "Coursework & SCOPE": {
                "score": scope_score,
                "tier": cw_tier,
                "reasoning": f"{cw_reason} {sem_eval['scope_articulation_reasoning']}"
            },
            "Academics & CPI": {
                "score": det_scores["Academics"],
                "tier": "Outstanding" if det_scores["Academics"] >= 18 else ("Very Good" if det_scores["Academics"] >= 14 else "Good")
            }
        }
    else:
        pillars = {
            "Academics & CPI": {
                "score": det_scores["Academics"],
                "tier": "Outstanding" if det_scores["Academics"] >= 18 else ("Very Good" if det_scores["Academics"] >= 14 else "Good")
            },
            "Branch Match": {
                "score": det_scores["Branch"],
                "tier": "Very Good" if det_scores["Branch"] >= 17 else ("Good" if det_scores["Branch"] >= 12 else "Neutral")
            },
            "Work Experience": {
                "score": sem_eval["work_experience_score"],
                "tier": sem_eval["work_experience_tier"],
                "reasoning": sem_eval["work_experience_reasoning"]
            },
            proj_label: {
                "score": sem_eval["projects_score"],
                "tier": sem_eval["projects_tier"],
                "reasoning": sem_eval["projects_reasoning"]
            },
            "SCOPE Articulation": {
                "score": sem_eval["scope_articulation_score"],
                "tier": sem_eval["scope_articulation_tier"],
                "reasoning": sem_eval["scope_articulation_reasoning"]
            },
            "Leadership & PoR": {
                "score": det_scores["Leadership"],
                "tier": "Very Good" if det_scores["Leadership"] >= 14 else "Average"
            }
        }

    # 7. Apply Role-Specific Mathematical Weighting Vector
    weights = ROLE_WEIGHTS[track]
    if track == "CORE_TECHNOM":
        weighted_content_score = (
            weights["Work Experience"] * (pillars["Work Experience"]["score"] * 5) +
            weights["Projects & Depth"] * (pillars[proj_label]["score"] * 5) +
            weights["Leadership & PoR"] * (pillars["Leadership & PoR"]["score"] * 5) +
            weights["Branch Match"] * (pillars["Branch Match"]["score"] * 5) +
            weights["Coursework & SCOPE"] * (pillars["Coursework & SCOPE"]["score"] * 5) +
            weights["Academics & CPI"] * (pillars["Academics & CPI"]["score"] * 5)
        )
    else:
        weighted_content_score = (
            weights["Academics & CPI"] * (pillars["Academics & CPI"]["score"] * 5) +
            weights["Branch Match"] * (pillars["Branch Match"]["score"] * 5) +
            weights["Work Experience"] * (pillars["Work Experience"]["score"] * 5) +
            weights["Projects & Depth"] * (pillars[proj_label]["score"] * 5) +
            weights["SCOPE Articulation"] * (pillars["SCOPE Articulation"]["score"] * 5) +
            weights["Leadership & PoR"] * (pillars["Leadership & PoR"]["score"] * 5)
        )
    content_score = round(weighted_content_score)

    # Final Composite Score: 85% Content + 15% Structural Layout
    final_score = round(0.85 * content_score + 0.15 * structural_score)

    if final_score >= 90:
        verdict = "Top 1% Day-1 Prime (God-Tier Contender)"
    elif final_score >= 80:
        verdict = "Outstanding (Strong Shortlist Contender)"
    elif final_score >= 70:
        verdict = "Very Good (Shortlist Contender)"
    elif final_score >= 58:
        verdict = "Good / Borderline (Needs Optimization)"
    else:
        verdict = "High Risk (Requires Major Revision)"

    return {
        "overall_score": final_score,
        "verdict": verdict,
        "content_score": content_score,
        "structural_score": structural_score,
        "extracted_signals": signals,
        "deterministic_scores": det_scores,
        "pillars": pillars,
        "semantic_benchmarks": semantic_match,
        "spo_layout_metrics": spo_metrics,
        # Geometry and appearance, reported separately so a reader can see which moved.
        "structural_geometric_score": struct_eval["score"],
        "structural_breakdown": struct_eval.get("breakdown"),
        "spo_layout_regions": struct_eval.get("regions") or {},
        "structural_visual": struct_eval.get("visual"),
        "structural_visual_weight": struct_eval.get("visual_weight", 0.0),
        "structured_resume": resume_json,
        # The exact content parse the extraction was performed from (the block
        # available, PyMuPDF blocks otherwise). Returned so the validation layer audits
        # grounding against the text the extractor actually read, rather than re-deriving
        # it with a different reader and reporting the difference as fabrication.
        # Additive: no existing consumer is affected.
        "raw_markdown": raw_markdown,
        # Which floors fired, why, and the evidence behind each. Empty when the
        # qualitative scores already cleared them.
        "evidence_adjustments": evidence_adjustments
    }
