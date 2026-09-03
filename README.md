<div align="center">

<img src="brand/resumetr-lockup.svg" alt="ResuMetr" height="64">

**Resume intelligence for IIT Kanpur placements.**
Upload one PDF, pick one of five placement tracks, and get a scored, validated,
evidence-grounded review — with every claim traced back to the page it came from.

<br>

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?style=flat-square&logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=000)
![TypeScript](https://img.shields.io/badge/TypeScript-strict-3178C6?style=flat-square&logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-8-646CFF?style=flat-square&logo=vite&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind-4-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white)

![Gemini](https://img.shields.io/badge/Gemini-3.6%20Flash-8E75B2?style=flat-square&logo=googlegemini&logoColor=white)
![PyMuPDF](https://img.shields.io/badge/PyMuPDF-layout%20%2B%20evidence-C41E3A?style=flat-square)
![PDF.js](https://img.shields.io/badge/PDF.js-viewer-E34F26?style=flat-square&logo=mozilla&logoColor=white)
![Radix UI](https://img.shields.io/badge/Radix_UI-accessible-161618?style=flat-square&logo=radixui&logoColor=white)
![Pytest](https://img.shields.io/badge/pytest-322%20passing-0A9EDC?style=flat-square&logo=pytest&logoColor=white)
![Figma](https://img.shields.io/badge/Figma-design%20system-F24E1E?style=flat-square&logo=figma&logoColor=white)

</div>

---

> **Deploying this?** [**DEPLOYMENT.md**](DEPLOYMENT.md) is a step-by-step,
> beginner-friendly guide to putting the frontend on **Vercel** and the backend on
> **Render** — including environment variables, CORS, free-tier limits and a
> troubleshooting section.

---

## What it does

A student uploads a resume and selects a target track. ResuMetr returns a composite score,
a pillar-by-pillar breakdown weighted for that track, prioritised recommendations, and —
for each recommendation — the exact bullet in the PDF it refers to, highlighted in place.

Two things make it different from a résumé grader:

**It checks its own work.** A validation agent runs before any score reaches a human and
traces every extracted organisation, degree, CPI figure and metric back to the raw PDF
text. A fabricated metric blocks the result outright rather than quietly inflating a
pillar.

**It refuses to tell you to make things up.** The recommendation agent runs a self-critique
pass, and the rules it enforces are enforced in code as well as in the prompt. "Add a 30%
improvement metric" is rejected before it can ever be shown; the rejection stays visible so
the pass can be audited.

---

## Architecture

Seven layers. The first five are the original scoring pipeline, unmodified.

```
  ┌─ 1  Physical layout & typography ──── resume_structure.py    margins, fonts, word count → 0-100
  │      └ visual layout reading ──────── predict.py            SigLIP vs. track references, or Gemini as a VLM
  │  2  Table & section extraction ────── resume_parser.py       PyMuPDF 2D block sort → 14-section JSON
  │  3  Deterministic hard signals ────── scorer_engine.py       CPI, branch, JEE AIR, CP rating, PoR tier
  │  4  Qualitative safety net ────────── scorer_engine.py       Gemini, bounded 0-20, fails loudly
  │  5  Role weighting matrix ─────────── scorer_engine.py       85% content + 15% layout
  ├─ 6  Validation agent ──────────────── validation_agent.py    grounding, consistency, never withholds
  └─ 7  Recommendation agent ──────────── recommendation_agent.py attribute → ground → self-critique
```

```
spo_recommendation_engine/
├── backend/
│   ├── app/                    API adapter, agents, derived layers
│   │   ├── llm.py              the single LLM entry point for the whole project
│   │   ├── validation_agent.py layer 6
│   │   ├── recommendation_agent.py  layer 7
│   │   ├── role_frameworks.py  loads the track articles into the prompt
│   │   ├── scholastic_signals.py  olympiads, ranks, fellowships
│   │   ├── impact_signals.py   quantified results
│   │   ├── evidence_floors.py  where hard evidence enters the score
│   │   ├── spo_config.py       guideline config loader
│   │   ├── tracks.py           canonical track registry
│   │   ├── kg_adapter.py       the only place company tiers are defined
│   │   ├── recommendations.py  deterministic rule engine
│   │   ├── report_sections.py  strengths, critical gaps, formatting fixes
│   │   ├── por_substance.py    reads a PoR on span, resources and turnout
│   │   ├── company_profile.py  sizes employers outside the graph
│   │   ├── compliance.py       SPO submission rules
│   │   ├── company_fit.py      shortlist-fit estimate
│   │   ├── evidence.py         resume text → PDF bounding boxes
│   │   └── pipeline.py         orchestration
│   ├── scoring/                layers 1-5, the CLI, and predict.py
│   ├── config/                 SPO guidelines, revised per cycle
│   ├── tools/                  fixture generator
│   └── tests/                  322 acceptance tests
├── frontend/                   React dashboard
├── knowledge-base/             role frameworks, SPO guidelines, signal corpora
├── recruiter-kg/               curated recruiter knowledge graph
├── brand/                      logo and usage
└── docs/                       the integration brief this was built against
```

---

## Quickstart

```bash
./run.sh
```

Starts the scoring API and the dashboard in live mode on **http://localhost:5173**. It
refuses to start without `GEMINI_API_KEY` in `backend/.env`, rather than launching a
dashboard that cannot evaluate. A full run takes 60–180s and makes six model calls.

### Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt


cp .env.example .env         # then set GEMINI_API_KEY
export GEMINI_API_KEY="..."

.venv/bin/python run_api.py  # http://127.0.0.1:8000
```

### Two readers, two jobs

The PDF is read twice, for different purposes, and the two are not interchangeable.

| Job | Reader | Why |
| --- | --- | --- |
| **Content** — text for the LLM extraction | `resume_parser.extract_pdf_markdown` — PyMuPDF block extraction, sorted top-to-bottom then left-to-right | The SPO template is multi-column. A flat text dump interleaves the columns; sorting blocks keeps each row's label attached to its value. |
| **Structure** — margins, fonts, spacing, word count | `resume_structure.RelaxedResumeParser` — PyMuPDF spans | Layout scoring needs glyph positions and font metrics, which a flattened content parse does not carry. |

`tests/test_extraction.py` asserts the split holds, so a future change cannot quietly
collapse them into one pass.

Block extraction preserves word spacing in LaTeX-justified text, where a naive read fuses
words together (`ComplexVariableAnalysis`, `DesignedaJEPA`). The extraction prompt handles
the SPO template's duplicated header table through its rule 7 ("keep only ONE copy" of a
repeated entry).

### Grounding audits the text the extractor read

`score_resume` returns `raw_markdown` — the exact content parse the extraction was
performed from — and the validation agent audits against **that**, not a fresh
`page.get_text()`. Auditing against a separately-produced dump makes content that only the
extractor's reader recovered look fabricated; on the reference resume that alone was the
difference between 93% and 100% grounding coverage.

The matcher also folds typographic variants (`×`/`x`, `→`, curly quotes) and tolerates
unit-spacing differences between the two reads — one writes `13.9 × compression`, the
other `13.9×` — while still requiring the numeric core to be present, so an invented
figure is caught.

### Frontend

```bash
cd frontend
npm install
npm run dev                  # http://localhost:5173
```

Vite proxies `/api` to the Python service, so the browser only ever talks to one origin
and the Gemini key never leaves the server.

### Without a Gemini key

```bash
echo 'VITE_USE_MOCK=true' > frontend/.env.local
```

Every panel renders from the bundled fixture, the header shows a **Fixture data** chip,
and the result carries a `MOCK_SESSION` warning. See [Fixture data](#fixture-data).

---

## Command reference

### CLI

```bash
cd backend/scoring

# score only
python run_evaluation.py resume.pdf --track SDE

# score, validate, and generate a grounded review
python run_evaluation.py resume.pdf --track SDE --validate --recommend

# write both machine and human output
python run_evaluation.py resume.pdf --track QUANT \
    --validate --recommend \
    --json_out results.json --md_out review.md

# summary only, no section dumps
python run_evaluation.py resume.pdf --track CONSULT_PM --validate --quiet
```

| Flag | Effect |
| --- | --- |
| `--track` | `ANALYST_AIML` · `CONSULT_PM` · `CORE_TECHNOM` · `QUANT` · `SDE`. Choices are generated from the canonical registry, never a second hardcoded list. |
| `--validate` | Runs layer 6 and reports its findings. Add `--strict` to exit 2 on a `NEEDS_REVIEW` verdict; by default the score is always printed. |
| `--recommend` | Runs layer 7. Runs regardless of the validation verdict — findings qualify the advice, they do not withhold it. |
| `--json_out` | Full result, including both agent reports. |
| `--md_out` | Candidate-facing Markdown review. |
| `--model` | Overrides the model for this run. |
| `--quiet` | Suppresses the section dumps. |

**Exit codes:** `0` produced · `1` pipeline failure · `2` validation blocked.

### Tests

```bash
cd backend && .venv/bin/python -m pytest tests -q
```

29 tests. The LLM-backed checks run with a stubbed auditor, so the suite is offline and
deterministic while still exercising both the confirmed and unconfirmed grounding paths.

### Other

```bash
# regenerate the sample PDF and the fixture
cd backend && .venv/bin/python tools/make_mock_fixture.py

# frontend
cd frontend
npm run typecheck
npm run build
npm run preview
```

---

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Capabilities, so the UI can disable evaluation and say why rather than failing at submit time. Reports whether a key is configured; never the key. |
| `GET /api/tracks` | The five tracks with weight vectors read from `ROLE_WEIGHTS`, so displayed weights cannot drift from the ones used to score. |
| `POST /api/evaluate` | `multipart/form-data` with `resume` (PDF) and `track`. |

The upload is written to a temp file for the duration of the request and deleted in a
`finally` block. It is never persisted, and never written to browser storage.

Errors return `{"error": {"code", "message", ...}}`. `SCORING_UNAVAILABLE`,
`SCORING_FAILED` and `MALFORMED_RESULT` all surface as visible failures. **No failure is
ever replaced with a plausible-looking score.**

---

## Layer 6 — validation agent

Ten named checks, each an independent function returning structured findings. Adding a
check means appending to a list, not editing a monolith. One failing check degrades to a
warning rather than taking down the report.

| Group | Checks |
| --- | --- |
| Grounding | Every organisation, degree, CPI and quantified metric in the extracted JSON traced back to the raw PDF text. Every sentence of the model's own justification checked for invented specifics. |
| Consistency | `ROLE_WEIGHTS` sums to 1.0 · pillar scores within 0–20 · CPI fail-closed policy actually applied · detected branch agrees with the Department field · PoR detection gap distinguished from genuine absence. |
| Integrity | Qualitative and corpus scorers diverging widely on the same pillar · the safety net's sanitiser filling in defaults instead of failing loudly · organisations absent from the recruiter graph. |

Grounding runs a deterministic token-coverage matcher first, which settles most claims for
free; only the residue costs a model call. **Every numeric token must be present** for a
claim to pass deterministically, because a fabricated metric is the failure mode that
actually moves a score. Prose is allowed to be a paraphrase.

| Status | Meaning |
| --- | --- |
| `PASS` | Every check clean. |
| `PASS_WITH_WARNINGS` | Nothing fabricated, but something needs a human's attention. |
| `NEEDS_REVIEW` | Something needs checking against the PDF before the score is relied on. The score is still shown, with the findings raised beside it. |

**Nothing is ever withheld.** An earlier version blocked the result outright, which turned
out to fire on the evaluator's own loose prose rather than on any fabricated fact — the
score was correct and the student saw nothing. Validation now qualifies a result instead of
replacing it, and `--strict` is available for pipelines that want a non-zero exit.

## Layer 7 — recommendation agent

Three explicit steps:

1. **Attribute.** Rank pillars by `weight × headroom`, so advice targets the highest-
   *leverage* fix rather than the lowest raw score, and compute the distance to the next
   verdict threshold.
2. **Ground.** The deterministic rules supply the spine; the model sharpens them against
   the candidate's actual text. It may add at most two new items, and only ones citing
   real resume content.
3. **Critique.** A second pass rejects anything that contradicts a validation finding,
   asks for a fabricated number, treats branch or PoR detection as an eligibility gate, or
   is generic filler.

Four rules are enforced **in code**, before the model is consulted, because a prompt is not
a guarantee:

- Never ask a candidate to invent, estimate or inflate a figure.
- Never treat branch or PoR-tier detection as an eligibility gate.
- Never name a `PPO_DOMINANT` firm as a campus application target — that channel does not
  exist.
- Never emit an item with no evidence reference.

Rejected drafts stay visible in the response and the UI. An agent that silently discards
its own output cannot be audited.

---

## Real vs. derived

`response.derived` names the ruleset behind every field the scoring engine did not
produce, and the UI renders that name on the panel.

**From `score_resume()`, unmodified:** `overall_score` · `verdict` · `content_score` ·
`structural_score` · `pillars` · `extracted_signals` · `spo_layout_metrics` ·
`structured_resume` · `semantic_benchmarks`

| Derived field | Ruleset | Produced by |
| --- | --- | --- |
| `recommendations[]` | `deterministic-rules-v1` | Named rules; each carries `source_rule`. No model call. |
| `evidence_refs[]` | `pymupdf-text-search-v1` | PyMuPDF search, normalised to 0–1 of the page box. |
| `compliance` | `spo-guidelines-v1` | The SPO guidelines PDF. |
| `company_fit` | `kg-tier-heuristic-v0` | Curated recruiter graph + this engine's own verdict thresholds. |
| `validation` | `validation-agent-v1` | Layer 6. |
| `agent_recommendations` | `recommendation-agent-v1` | Layer 7. |

### Quantified impact

The numbers a candidate reports are what turn *described the work* into *showed what it
achieved*, so they are extracted as a first-class signal in the same shape the corpora
use:

```json
{"metric": "compression", "direction": "achieved", "value": 13.9, "unit": "x"}
```

`app/impact_signals.py` is deterministic — no model call — and publishes into
`signals["quantified_results"]`. Because `signals` is already serialised into the
qualitative evaluator's `HARD SIGNALS` prompt block, **the evaluator sees exactly which
figures the resume reports** when it scores SCOPE articulation and work-experience
impact. That required no change to the prompt or the wrapper.

The headline number is the *ratio*, not the count: twelve metrics across four bullets is
a different resume from twelve across twelve, and the ratio is what the SCOPE pillar is
really measuring.

What it deliberately rejects, with tests for each: model and dataset identifiers
(`LLaMA-2-7B`, `CIFAR-10`), design details (`16 4-bit centroids`), and years. A metric
name only attaches loosely to a number carrying a **measured** unit — `4.1 s` reads as
latency, but `12M daily events` is sizing the work, so no distant metric name attaches
to it.

### SPO guidelines are configuration, not code

The guidelines are revised each placement cycle — word counts, font rules and which items
are forbidden on a submitted resume all move — so they live in
`backend/config/spo-guidelines.json`.

```jsonc
{
  "cycle": "2026",
  "layout": { "min_words": 500, "max_words": 750, "min_content_font_size_pt": 9.0,
              "max_font_families": 1, "min_margin_in": 0.5, "name_min_ratio": 2.0 },
  "compliance_rules": {
    "SPO_NO_JEE_GATE_RANK": { "enabled": true, "severity": "BLOCKING", "guideline": "p.1 — ..." },
    "SPO_PREFERRED_FONT":   { "enabled": false, "severity": "INFO", "guideline": "p.4 — ..." }
  },
  "approved_headings": [ "..." ],
  "preferred_fonts": [ "Times New Roman", "..." ]
}
```

Per rule you can change `enabled`, `severity`, and the wording. **Disabling keeps the
rule's text**, so one dropped this cycle can be restored the next without rewriting it.
`layout` feeds `resume_structure.RelaxedResumeParser`; the compliance rules feed
`app/compliance.py`.

To run a different cycle: copy the file, edit it, and set `SPO_GUIDELINES_PATH`. Nothing
in the code changes. A missing or malformed file degrades to the shipped defaults rather
than crashing, and every compliance report names the `cycle` it was produced against plus
any `rules_disabled`. `GET /api/health` reports the same.

`SPO_PREFERRED_FONT` ships **disabled**: the SPO does not restrict template choice and
LaTeX Computer Modern is widely accepted in practice. Enable it if a cycle enforces the
list.

### Role frameworks reach the evaluator

`ROLE_RUBRICS` is a compact rubric — 804 to 2,448 characters. The articles in
`knowledge-base/role-frameworks/` are what the signal corpora were labelled against:
9,349 to 15,392 characters of tier definitions, the SCOPE worked example, articulation
principles, red flags and IITK institutional context.

`app/role_frameworks.py` loads the framework at runtime and the scorer **appends** it to
the system prompt. `ROLE_RUBRICS` is byte-identical and still leads, owning the scoring
bands; the framework decides *where inside a band* a candidate falls.

| Track | Rubric alone | With framework |
| --- | ---: | ---: |
| ANALYST_AIML | 804 | 11,515 (14×) |
| CONSULT_PM | 811 | 16,869 (21×) |
| QUANT | 907 | 12,195 (13×) |
| SDE | 2,448 | 13,175 (5×) |
| CORE_TECHNOM | 2,450 | 11,799 (5×) |

Missing frameworks degrade silently to the previous behaviour, and `GET /api/health`
reports which loaded.

### Visual layout scoring

`resume_structure.py` always imported `predict.AestheticScorer`, and `pdf_to_pngs()` was
written to feed it, but the module did not exist — so `HAS_AESTHETIC_SCORER` was always
false and the structural score was purely geometric. `backend/scoring/predict.py` fills
that hook. The geometric metrics are unchanged; the visual reading sits beside them.

| Backend | What it does | Requires |
| --- | --- | --- |
| **SigLIP** | Embeds the rendered page and scores it by cosine similarity to the centroid of accepted resumes **for that track** | `transformers` + `torch`, and a reference image set |
| **VLM** | Sends the page image to Gemini for a layout judgement against SPO conventions | a model key |

`auto` prefers SigLIP, because comparing against accepted resumes for the same track is a
stronger signal than a general judgement, and falls back to the VLM.

**SigLIP is not active.** It needs a directory of accepted resume images per track, which
the repository does not ship — the signal corpora are text only, with no page images to
embed. Point `REFERENCE_RESUMES_DIR` at
`<dir>/<TRACK>/*.png` and it turns on with no code change. `GET /api/health` reports
which backend is live.

`score` stays the geometric value every existing consumer reads; `composite_score` blends
in the visual reading at `layout.visual_weight` (default 0.2) **only when a backend
actually ran**, so the default path is unchanged.

### Scholastic achievements

The Scholastic Achievements section carries some of the strongest signals on an IITK
resume, and the deterministic layer was detecting almost none of it. `has_olympiad` was a
single boolean over nine acronyms — a state screening exam and an international medal
scored identically — and IOQM, NSEP, NSEC, state entrances, NEET and admission offers
were invisible.

`app/scholastic_signals.py` tiers each achievement using the frameworks' own bands:

| Signal | Bands | Source |
| --- | --- | --- |
| Olympiad | international / camp → Outstanding · national → Very Good · qualifier → Good | `quant.txt §3` |
| JEE Advanced AIR | <200 · <500 · 500–1000 · **>1500 diluting** | `quant.txt §2.1` |
| Any ranked exam with a stated cohort | top 0.25 pct → Outstanding · top 0.5 pct → Very Good · **>2% diluting** | `consult_pm.txt §2.A` |
| Awards, fellowships, admission offers | named scholarships and research fellowships → Outstanding | frameworks |

Two things worth calling out. A rank binds to the **nearest** exam, not the first listed —
*"642/720 in NEET … and Rank 40 in WBJEE"* is WBJEE's rank. And **weak ranks are reported
as diluting**, because `consult_pm.txt` is explicit that a moderate rank beside a strong
one hurts and `quant.txt` advises omitting an AIR above 1500 entirely.

Every signal carries the `basis` for its call, so a reviewer can check it against the
framework. The original booleans are untouched.

### Recruiter matching

The panel answers *which recruiters are worth targeting*. It previously derived fit from
the composite score alone, so **every Tier-1 firm scored identically** and the five shown
were effectively arbitrary.

Ranking now lives in `kg_adapter.match_recruiters` — with the graph data, not in a module
beside it — and reads the **built export** rather than the seed:

| | Seed | Built export |
| --- | ---: | ---: |
| Companies | 78 | 207 |
| SDE recruiters | 31 | 79 |
| Observed IITK recruiting | — | per cycle, per role |
| Per-firm branch affinity | — | yes |

Build it once with `cd recruiter-kg && python3 iitk_kg.py build`. The seed stays the
fallback, so the pipeline runs before anyone has built it — with tiers only.

Three observed signals separate firms that share a tier:

- **`presence_strength`** — how much the firm actually recruited at IITK for this role
- **`branch_affinity`** — the share of its IITK hiring that came from this branch
- **`evidence_strength`** — the graph's own shrinkage, so a thin observation moves the
  ranking less

Ordering is **tier first**, then fit, then observed presence. A firm the builder left
untiered sorts last, labelled *Tier not curated* — giving it Tier-4's easy bar made
uncurated startups outrank Google, which was the first thing this got wrong.

Branch is **history, never a gate**, as the graph's README requires: it nudges ordering
and is quoted as *"36% of its IIT Kanpur hiring last cycle came from EE"*. It never
excludes anyone, and a test asserts the wording never implies eligibility.

The result responds to the candidate — for SDE at 76/100 an EE candidate sees Oracle
first, a CSE candidate sees Databricks.

### Evidence floors — where hard evidence enters the score

Scholastic achievements, quantified impact and company pedigree do not only inform the
prompt; they set deterministic **floors** on the three pillars they carry direct evidence
for.

`ROLE_RUBRICS` already states what the evidence is worth — *"Tier-1 (18-20 pts)"* — so
when the knowledge graph independently confirms a firm is Tier-1 for the target role, an
18 floor **enforces the rubric rather than overriding it**.

| Pillar | Evidence | Floor |
| --- | --- | ---: |
| Work Experience | KG tier 1 for this role | 18 |
| Work Experience | KG tier 2 | 14 |
| Work Experience | KG tier 3 | 10 |
| SCOPE Articulation | ≥60% of bullets state a measured result | 16 |
| SCOPE Articulation | ≥35% | 13 |
| Academics & CPI | scholastic profile reaches Outstanding | 17 |
| Academics & CPI | reaches Very Good | 15 |

Academics floors are deliberately conservative: every IITK candidate cleared JEE
Advanced, so only genuinely rare achievements move one. A diluting entry never lowers
anything — it surfaces as advice instead.

On CORE_TECHNOM the SCOPE floor is recorded against `Coursework & SCOPE`, the blended
pillar that track actually uses, so the adjustment stays visible in the UI.

Three rules keep this safe, each with tests:

1. **Floors never lower a score.** The evaluator may always score higher.
2. **Floors sit at the bottom of the band**, never its midpoint — they guard against
   under-crediting real evidence, not a way to inflate.
3. **Every application is recorded** in `evidence_adjustments` with the evidence that
   triggered it, and the UI shows `13 → 18 from hard evidence` on the pillar itself.

The tier is per-role, so the same internship counts differently by target: Texas
Instruments floors Work Experience at 14 for SDE and 18 for CORE_TECHNOM, and not at all
for QUANT where the graph has no edge for it.

**On the `pedigree_for` edge:** the KG's two edges are not interchangeable —
`pedigree_for` means "an internship here is a positive signal when applying for this
role", which is exactly this question, so it is preferred. It is populated for only 10 of
78 companies, so `recruits_for` is the documented fallback and every adjustment records
`edge_is_fallback` so the two are never conflated.

### What was left intact, deliberately

The original scoring scripts are the source of truth for signal format. Verified untouched:

| File | Status |
| --- | --- |
| `resume_parser.py` | Untouched — extraction prompt, `RESUME_SCHEMA` and the Gemini wrapper are verbatim |
| `resume_structure.py` | Untouched |
| `semantic_signal_matcher.py` | Untouched |
| `scorer_engine.py` | 3 edit sites; `ROLE_RUBRICS`, `evaluate_semantic_with_safety_net`, the sanitisers, `ROLE_WEIGHTS` and `score_resume` all unchanged |
| `run_evaluation.py` | Rewritten as the CLI, per brief §6 |

`signals["detected_analyst_firms"]` keeps its original 12-firm regex behaviour exactly,
because the extracted signal corpora were produced against it and its values must stay
comparable. Knowledge-graph resolution is published additively under `kg_pedigree_firms`
and `kg_unverified_firms`, so §3.1's "flag an unverified company" is satisfied without
altering a value the scorer already emitted.

### Still open

`semantic_signal_matcher.py` still does substring containment rather than embedding
similarity (brief §3.2), and `ROLE_RUBRICS` prompt text still carries its own company
lists rather than generating them from the graph at prompt-build time (§3.1). Both are
left as-is on purpose: changing either would shift the qualitative scores away from the
corpora they were calibrated against.

---

## How evidence maps to PDF coordinates

1. A rule attaches the **verbatim** text it fired on — usually a resume bullet straight out
   of `structured_resume`.
2. `PdfEvidenceLocator` searches the PDF with PyMuPDF's `search_for`. If the exact string
   misses, it retries with progressively shorter prefixes, since the head of a bullet is
   the reliable part.
3. Hits are stored **normalised to 0–1** of the page box, so the overlay tracks the canvas
   at any zoom and any device pixel ratio:

   ```json
   { "page": 1, "x": 0.0916, "y": 0.2867, "width": 0.5634,
     "height": 0.0143, "text": "...", "match": "exact" }
   ```
4. Cards and highlights share the recommendation `id`, so hover, keyboard focus and pinning
   all resolve to the same target.
5. **When nothing matches, no box is emitted.** The card reads *No evidence location* and
   the viewer says *Evidence location unavailable*. A nearby region is never highlighted as
   a substitute.

`meta.evidence_resolved` / `meta.evidence_requested` report the hit rate per run.

---

## The two signature readouts

**SCOPE meter.** The role frameworks judge every bullet on Scale, Context, Own, Proof and
Edge. The backend reports which of the five a specific bullet carries, so the advice can
name the missing dimension instead of saying "add more metrics".

**Leverage bars.** In the pillar breakdown, each bar's *track width is the pillar's weight*
and the *fill is its score*. Filled area is the pillar's contribution to the content score;
the empty remainder is the headroom, and it is the same number the recommendations quote as
expected impact. A 25%-weight pillar's bar is five times the width of a 5% one.

---

## Environment

### Backend — `backend/.env`

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | — | **Required.** Read server-side only; never serialised into a response. |
| `GEMINI_MODEL_NAME` | `gemini-3.6-flash` | One value for the whole process. Every LLM call in the project goes through `app/llm.py`. |
| `MAX_UPLOAD_BYTES` | `8388608` | Upload cap, reported via `/api/health` so client and server agree. |
| `CORS_ORIGINS` | `http://localhost:5173,…` | Comma-separated allowed origins. |
| `SCORING_DIR` | `backend/scoring` | Where the scoring modules live. |
| `KG_COMPANIES_PATH` | `recruiter-kg/companies.seed.json` | Recruiter graph seed. |

### Frontend — `frontend/.env.local`

| Variable | Default | Purpose |
| --- | --- | --- |
| `VITE_USE_MOCK` | `false` | `true` serves the bundled fixture instead of calling the API. |
| `VITE_API_BASE_URL` | `""` | Set when the API is not behind the dev proxy. |
| `VITE_API_PROXY_TARGET` | `http://127.0.0.1:8000` | Dev proxy target. |

> No secret belongs in any `VITE_*` variable — Vite inlines them into the client bundle.

---

## Fixture data

`backend/tools/make_mock_fixture.py` regenerates both the sample PDF and the fixture.

The resume is fictional. Everything downstream of it is real: layout metrics from
`RelaxedResumeParser`, hard signals from `extract_deterministic_signals`, the validation
report from the real agent, the critique pass from the real hard-rule gate, and every
evidence bounding box from the real locator run against the generated PDF. **Only the
three Gemini-scored pillars are stand-in values**, and `meta.is_mock` is `true`.

The fixture deliberately includes two drafts that violate the hard rules — a fabricated
metric and a PPO-dominant campus suggestion — so the rejection path is demonstrated, not
just the happy one.

The mock service lives in `frontend/src/mocks/` and is reachable only through
`VITE_USE_MOCK`. A production response and fixture data can never merge into one result.

---

## SPO submission compliance

The composite score already includes five physical guidelines measured by
`resume_structure.py`. `compliance.py` adds the submission rules that are pass/fail policy
rather than a gradient, so they must not be folded into a score: no mobile number, no
JEE/GATE rank, page count, black-only text, CPI/XII/X in the education table, reverse
chronological order, years on achievements, self-projects labelled, ongoing work marked.

One conflict is reported rather than resolved silently: **the guidelines forbid a JEE rank
on a submitted resume, while the scorer awards up to +3 academic points for one.** When
both fire, the finding says so, so the student knows removing it is required for submission
and will lower the modelled score.

---

## Design system

The Figma file was generated **from** this codebase, not ahead of it:

**[figma.com/design/nyqyH3O0iA62J4UglDJVr1](https://www.figma.com/design/nyqyH3O0iA62J4UglDJVr1)**

70 variables across 5 collections, 9 text styles, 4 effect styles, 16 pages. Every variable
carries WEB code syntax in `var(--token)` form matching `frontend/src/styles/tokens.css`
exactly, so a change on either side can be reconciled with the other.

- **`Colour` has a single `Light` mode.** The brief specifies a light glassmorphism system
  and the code defines one palette, so no dark values were invented.
- **`Data/Eyebrow` uses JetBrains Mono Bold in Figma, weight 600 on the web.** Figma ships
  no SemiBold static cut locally; `tokens.css` is correct.
- `--colour-ink-faint` was darkened from `#7d8bab` to `#606d87` during the accessibility
  audit — the original measured 3.32:1 on glass, below AA for the 10px meta text it
  carries.

---

## Accessibility

Hover is never the only route to the evidence link: cards are focusable and respond to
Enter and Space, and every tooltip trigger is keyboard-reachable. All text colours clear
WCAG AA against glass, sunken and bare ground. Motion is limited to state transitions, the
active highlight and the score reveal, and `prefers-reduced-motion` disables all of it,
including the count-up.
