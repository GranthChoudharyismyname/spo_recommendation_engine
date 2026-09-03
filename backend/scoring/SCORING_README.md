# IIT Kanpur Placement Resume Scoring Engine

A modular, evaluation-safe AI scoring and diagnostic pipeline built specifically for IIT Kanpur (IITK) recruitment across 5 placement tracks.

## Architecture

The pipeline consists of 5 tightly integrated layers:

1. **Physical Layout & Typography (`resume_structure.py`)**:
   - `RelaxedResumeParser`: Evaluates SPO (Students' Placement Office) formatting guidelines (margins, font sizes, LaTeX Computer Modern fonts, word count, name ratio) on a 0–100 structural score with fail-closed blank document handling ($<50$ words $\to 0/100$) and one-sided name ratio penalty.
2. **Table & Section Extraction (`resume_parser.py`)**:
   - PyMuPDF 2D spatial block sorting preserves 100% of word spaces in LaTeX justified documents and extracts tables cleanly into markdown.
   - LLM structured schema parses text into a strict 14-section JSON format.
3. **Deterministic Hard Signal Extraction (`scorer_engine.py`)**:
   - Scoped extraction of CPI (scale-adjusted, missing CPI strictly penalized with unverified baseline), Branch match (track-prioritized), JEE Advanced AIR, Codeforces ratings (platform-scoped), Scholarships, and official IITK Students' Gymkhana 7-tier PoR hierarchy.
4. **Qualitative Safety Net Evaluator (`scorer_engine.py`)**:
   - Uses Gemini to assess project depth, work experience pedigree, and SCOPE metric articulation under role-specific prompt rubrics with strict type/enum sanitization and bounds clamping ($0–20$). Fails explicitly on API error without fabricating scores.
5. **Role-Specific Mathematical Weighting Matrix**:
   - Computes a weighted content score using custom weight vectors for all 5 placement tracks.
   - Master Composite Score = 85% Weighted Content + 15% Physical Layout.

---

## Supported Placement Tracks & Exact Mathematical Weights

| Track Code | Domain | Primary Focus & Weight Distribution |
| :--- | :--- | :--- |
| `ANALYST_AIML` | Analytics & Applied AI/ML | Work Ex (25%), ML Projects (25%), Academics (20%), SCOPE metrics (15%), Branch (10%), PoR (5%) |
| `QUANT` | Quantitative Finance & HFT | Academics/CPI & Spikes (35%), Systems/Math Depth (25%), Work Ex (20%), Branch (10%), SCOPE (5%), PoR (5%) |
| `CONSULT_PM` | Management Consulting & PM | Leadership & PoR (25%), Work Ex (25%), Strategic Projects (20%), Academics (15%), SCOPE (10%), Branch (5%) |
| `CORE_TECHNOM` | Core Engineering & TechnoM | Work Ex (25%), Core Projects & Mentorship (20%), Ground PoR (20%), Branch (15%), Coursework & SCOPE (10%), Academics (10%) |
| `SDE` | Software Development Engg | Work Ex (25%), Projects & Systems Depth (20%), Academics (20%), Branch (15%), SCOPE Precision (10%), Leadership & PoR (10%) |

---

## Installation

```bash
pip install pymupdf Pillow google-genai requests certifi
# Or install via requirements.txt
pip install -r requirements.txt
```

---

## Quickstart / Usage

### Run via Command Line

```bash
# Set your API Key
export GEMINI_API_KEY="your_gemini_api_key"

# Evaluate an Analyst Resume
python run_evaluation.py resume_analyst.pdf --track ANALYST_AIML

# Evaluate a Core / Techno-Management Resume
python run_evaluation.py resume_core.pdf --track CORE_TECHNOM

# Evaluate an SDE Resume
python run_evaluation.py resume_sde.pdf --track SDE

# Save evaluation results to a JSON file
python run_evaluation.py resume.pdf --track SDE --json_out results.json
```
