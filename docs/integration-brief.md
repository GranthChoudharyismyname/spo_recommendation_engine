# Prompt: Wire the IITK Resume Scoring Pipeline + Build an Agentic Validation & Recommendation Engine

*Copy everything below this line into a fresh Claude session (Claude Code or Claude with
computer/file access) that has the following files uploaded: `README.md`,
`requirements.txt`, `resume_structure.py`, `resume_parser.py`, `scorer_engine.py`,
`semantic_signal_matcher.py`, `run_evaluation.py`, `analyst_signal_dictionary.json`,
`sde_signal_dictionary.json`, `core_signal_dictionary.json`,
`consulting_signal_dictionary.json`, `quant_signal_dictionary.json`, and
`iitk-recruiter-kg.zip`.*

---

## 0. Mission

You are integrating a resume-scoring pipeline for IIT Kanpur placements. The pieces
were built independently and **do not currently talk to each other correctly**. Your
job has two parts:

1. **Wire the existing modules into one coherent, consistent pipeline** — including a
   knowledge graph that is fully built but completely disconnected from the scorer.
2. **Build a new agentic validation and recommendation layer** on top, that (a) checks
   the pipeline's own output for internal contradictions and hallucination before it
   reaches a human, and (b) turns the score breakdown into specific, evidence-grounded
   recommendations for the candidate.

Do not treat this as "add a wrapper." Several of the integration issues below are
correctness bugs (silent mismatches, dead code paths, hardcoded data that duplicates a
source of truth) that will produce wrong scores if left alone. Fix root causes.

Read every file fully before writing code. Then produce a short written plan (module
list + data flow diagram in prose) and confirm it against Section 6's acceptance
criteria before implementing.

---

## 1. What you're actually looking at (verified inventory)

| File | Role | Status |
|---|---|---|
| `resume_structure.py` | `RelaxedResumeParser` — PyMuPDF layout metrics (margins, font, word count, name ratio) → 0–100 structural score | Self-contained, working |
| `resume_parser.py` | PDF → markdown (PyMuPDF block sort, optional Lexoid) → Gemini structured extraction into `RESUME_SCHEMA` | Self-contained, working. `HAS_LEXOID` and `HAS_NEW_GENAI` are soft-optional — verify both code paths actually work, not just the happy path |
| `semantic_signal_matcher.py` | Loads one of 5 role signal dictionaries, does **substring/keyword matching** (not semantic similarity despite the module name) against `evidence` text to score work-ex/projects/SCOPE 0–20 | Working but crude — see §3.2 |
| `scorer_engine.py` | Orchestrates: structure eval → PDF→JSON → deterministic signals (CPI, branch, JEE rank, Codeforces, scholarships, PoR tier) → semantic benchmark match → Gemini qualitative safety net → role-weighted composite score | Working, but **company/tier data is hardcoded in three separate places** that all disagree with the KG (see §3.1) |
| `run_evaluation.py` | CLI entry point calling `score_resume()` | Working, thin |
| `*_signal_dictionary.json` (5 files) | Corpora of signals mined from real candidate resumes per track (`267/234/113/72/?` signals), each with `raw_signal_label`, `signal_type` (outstanding/very_good/good/neutral/negative_diluting), `section`, `evidence`, `scope`, `impact`, `entities`, `candidate_source`, plus a `positive_spikes_registry` subset | Static data, partially used (see §3.2) |
| `iitk-recruiter-kg.zip` → `iitk_kg.py` + 3 seed JSONs | A **separate, fully-built SQLite CLI tool**: 78 curated companies with `recruits_for`/`pedigree_for` edges and 1–4 tiers per role, 42 institutions (pedigree entities), 30 departments + 24 programs, k-anonymized branch-affinity aggregates pulled from the live SPO stats feed | **Built and correct, but never imported or called by anything in `scorer_engine.py`.** This is the biggest integration gap. |

---

## 2. Read the KG tool carefully before touching it

`iitk_kg.py` is opinionated and the opinions matter — do not flatten them away when you
wire it in:

- **Two edge types, never collapse them.** `recruits_for` = this firm hires for this
  role at IITK, drives campus recommendations. `pedigree_for` = an internship there is
  a positive *signal* when scoring past work experience, but must never be surfaced as
  "you could get an offer here." `scorer_engine.py`'s `ROLE_RUBRICS` text currently
  mixes firms like Jane Street/Citadel/D.E. Shaw (PPO-dominant, effectively
  `pedigree_for` in spirit) with names implying they're campus targets. When you
  replace the hardcoded lists, preserve this distinction explicitly in whatever data
  structure you pass into the qualitative-eval prompt and the deterministic scorer.
- **Branch affinity is evidence, never a gate.** The KG's own README states this in
  bold: *"Render it as history, never as a criterion."* `det_scores["Branch"]` in
  `scorer_engine.py` is currently a hard-coded point value per branch — that's fine to
  keep as the primary mechanism, but if you use KG branch-affinity data anywhere
  (recommendations, validation context) it must be phrased as "this firm hired
  primarily from X branch last cycle" and never as "you are/aren't eligible."
- **`PPO_DOMINANT` firms are supposed to be nearly absent from placement data.** If your
  validation layer later notices zero campus openings for Jane Street/Optiver/D.E. Shaw
  under `QUANT`, that is correct behavior, not a bug — don't "fix" it.
- **Privacy contract is non-negotiable and already enforced in the KG's own code**
  (no PII ever written, k-anonymity suppression, UG-only via roll-number-length
  detection with the number then discarded). Do not build any code path that could
  re-attach a `candidate_source` ID from the signal dictionaries to a real identity.
  Treat `candidate_source` values purely as opaque grouping keys for calibration, never
  surface them to end users.
- **The KG has its own role vocabulary**: `SDE, QUANT, ANALYST, CONSULT, CORE`. The
  scorer has: `SDE, QUANT, ANALYST_AIML, CONSULT_PM, CORE_TECHNOM`. **These do not
  match.** You must build one canonical mapping table, used everywhere, not two
  ad-hoc `if` branches in different files.
- Run `python3 iitk_kg.py build` (or the granular `init → seed → fetch → ingest →
  export` steps) yourself once to produce a concrete `export.json`, and inspect its
  actual shape (`companies[]` with `recruits_for`, `pedigree_for`, `iitk_presence`,
  `branch_affinity`, `evidence_strength`, plus top-level `role_branch_signals` /
  `branch_role_signals` rollups) before designing the adapter. Don't guess the schema
  from the README description alone — the `fetch` step depends on a live URL
  (`iitk-spo26.netlify.app/data/stats.json`); if it's unreachable in your environment,
  build against `--mode raw` output structure from `cmd_export` in `iitk_kg.py` (read
  the function directly, it's fully commented) and mock a small fixture for tests.

---

## 3. Phase 1 — Integration (fix before adding anything new)

### 3.1 Replace hardcoded company/tier data with the KG

Currently there are **three independent, disagreeing sources of "which companies are
Tier 1 for which track"**:

1. `ROLE_RUBRICS` free-text blocks in `scorer_engine.py` (fed to Gemini as a prompt —
   e.g., QUANT Tier-1 lists "Quadeye, Graviton, Tower, AlphaGrep, Carlsen, D.E. Shaw,
   WorldQuant, Squarepoint, NK Securities").
2. `known_analyst_firms` list inside `extract_deterministic_signals()`.
3. Keyword lists inside `semantic_signal_matcher.py`'s `match_candidate_against_signal_corpus`
   (e.g., `"quadeye", "quant", "d.e. shaw", "worldquant"` string checks).

None of these read from `iitk-recruiter-kg.zip`. Fix:

- Build a small adapter module, e.g. `kg_adapter.py`, that loads the KG's exported JSON
  (call it once at process start, cache in memory; do not shell out to `iitk_kg.py` per
  resume) and exposes a clean API such as:
  - `get_company_tier(name_or_alias: str, role: str, edge_type: str = "recruits_for") -> Optional[CompanyTierInfo]`
    — must resolve through the KG's `aliases` list, not just exact display names.
  - `get_pedigree_tier(name_or_alias: str, role: str) -> Optional[CompanyTierInfo]`
  - `get_branch_affinity(company_id: str) -> list[BranchAffinity]`
  - `map_scorer_track_to_kg_role(track: str) -> str` and the inverse — this is the
    canonical mapping table from §2, defined once, imported everywhere.
- Replace the three hardcoded lists with calls into this adapter:
  - In `extract_deterministic_signals()`, resolve each Work Experience organization
    string against `get_pedigree_tier()` for the current track instead of the fixed
    `known_analyst_firms` list; feed the resolved tier into `det_scores` or into
    the Gemini qualitative prompt context (your call, but be consistent and document
    the choice).
  - In `semantic_signal_matcher.py`, replace the inline keyword arrays with lookups
    into the KG for company recognition; keep the domain-technical-term keyword
    lists (e.g., "backtester", "gradient boosting") since those aren't company names
    and the KG has no opinion on them.
  - In the `ROLE_RUBRICS` prompt text sent to Gemini, generate the Tier-1/2 company
    lists **dynamically from the KG at prompt-build time** instead of hardcoding them
    in the docstring, so the rubric and the deterministic layer can never drift apart
    again. Preserve the qualitative tone/structure of the existing rubric text — you're
    replacing the data source, not rewriting the pedagogy.
  - Where a company appears in a resume but is **not found in the KG at all**
    (`iitk_presence` would be `not_observed_at_iitk` or simply absent), do not silently
    score it as tier-unknown-neutral — surface this explicitly as a signal the
    validation layer (Phase 2) should flag, since it may indicate either a legitimate
    small/foreign firm or a hallucinated organization name from the PDF extraction.

### 3.2 Make `semantic_signal_matcher.py` do what its name says

It currently does substring containment checks between a fixed keyword list and lowercased
resume text — this is not semantic matching and it will both over- and under-match (e.g.
"transformer" from the keyword list will match a resume mentioning "transformer coupling"
in a mechanical engineering context). Improve it:

- At minimum, replace raw substring matching with matching against the actual
  `raw_signal_label`, `evidence`, and `entities` fields of each signal dictionary
  entry using an embedding similarity (reuse the Gemini embeddings API already
  available via `google-genai`, or `sentence-transformers` if you'd rather stay
  offline — pick one and justify it in a code comment) between the candidate's
  bullet-level text and each corpus signal's `evidence` string, thresholded per
  `signal_type` tier.
- Preserve the existing function signature and return shape
  (`match_candidate_against_signal_corpus(resume_json, raw_text, track) -> dict`) so
  `scorer_engine.py` doesn't need to change its call site, but do change the internals.
  If a fully embedding-based approach is infeasible in the target environment (no
  internet, no compute), implement a hybrid: exact/fuzzy entity-name matching (e.g.
  `difflib.SequenceMatcher`, already a KG dependency pattern to mirror) plus TF-IDF
  cosine similarity between bullet text and each signal's `evidence`, which needs no
  external API.
- Keep `positive_spikes_registry` matching as a distinct, higher-bar tier (used later
  by the recommendation engine as "what outstanding looks like" exemplars) — don't
  merge it into the general corpus matching.
- Add a confidence/evidence-strength value to the returned match info, mirroring the
  KG's own `evidence_strength` pattern (`_shrink(n)`), so thin matches (1 weak keyword
  hit) don't get the same weight as a rich, multi-signal match.

### 3.3 Consistency cleanup

- **Model name drift**: `resume_parser.py`, `run_evaluation.py`, and `scorer_engine.py`
  all default to `"gemini-3.6-flash"` in different places. Centralize this into one
  config constant/env var (`GEMINI_MODEL_NAME`), don't leave four copies to fall out of
  sync.
- **Optional-import handling**: `resume_parser.py` (`HAS_LEXOID`), `resume_structure.py`
  (`HAS_AESTHETIC_SCORER`, and the `predict.AestheticScorer` import that appears
  imported but never actually used anywhere in the file — confirm this and either wire
  it into `eval_all()`/`calculate_structural_score()` or remove the dead import), and
  both files' `HAS_NEW_GENAI` legacy fallback all need actual test coverage of the
  fallback branch, not just the primary path. Add a small `config.py` or `.env.example`
  documenting every optional dependency and what degrades if it's missing.
- **Track validation**: `run_evaluation.py`'s argparse `choices` and `ROLE_WEIGHTS.keys()`
  in `scorer_engine.py` must be generated from a single source of truth, not duplicated.
- **Define one canonical `EvaluationResult` schema** (a dataclass or TypedDict) for what
  `score_resume()` returns, and use it as the shared contract between the scorer, the new
  validation agent, and the new recommendation agent. Don't let the agents parse the raw
  dict ad hoc.

---

## 4. Phase 2 — Agentic Validation Engine

Build a new module, e.g. `validation_agent.py`, that runs **after** `score_resume()`
completes and before the result is shown to anyone. This is not a single regex pass —
structure it as a small agent loop with distinct, named checks, each producing a
structured finding, because future checks will need to be added without rewriting the
whole thing.

### 4.1 What it must check

**Grounding / hallucination checks** (compare `structured_resume` JSON and
`sem_eval` reasoning strings back against `raw_markdown`, the actual extracted PDF text):
- Every organization name, degree, CPI figure, and quantified metric that appears in
  `structured_resume` should be traceable to a substring (fuzzy-matched, allowing minor
  formatting differences) in `raw_markdown`. Flag anything that isn't — this is the
  #1 failure mode of PDF→JSON LLM extraction (invented dates, merged/split entries,
  fabricated metrics).
- Every claim inside `sem_eval["work_experience_reasoning"]`,
  `["projects_reasoning"]`, `["scope_articulation_reasoning"]` (the Gemini qualitative
  safety-net's free-text justifications) must reference something actually present in
  `structured_resume` or `raw_markdown` — the safety-net model should not be inventing
  justification for a score.

**Internal consistency checks**:
- `ROLE_WEIGHTS[track]` values sum to 1.0 (protects against a future typo silently
  changing the composite formula).
- Every pillar score is within its declared bound (0–20 for content pillars, 0–100 for
  structural).
- CPI-missing fail-closed logic (`acad_score = 4` when `cpi is None`) is actually being
  applied when it should be — cross-check `signals["cpi_status"]` against
  `det_scores["Academics"]`.
- Detected `branch` disagrees with `Department` field of `structured_resume` — flag
  as ambiguous rather than silently picking one.
- A company detected in Work Experience resolves to **no KG entry at all** (post-3.1)
  — flag as `UNVERIFIED_COMPANY`, not an error, just a note for a human/recommendation
  layer.
- PoR tier detection (`por_tier`) found a PoR-shaped entry in the resume but matched no
  regex pattern (`por_tier == 8` despite `por_entries` non-empty) — likely means the
  7-tier hierarchy list is incomplete, not that the candidate has no PoR. Flag distinctly
  from "genuinely no PoR."
- Gemini qualitative score (`sem_eval`) and deterministic/semantic-corpus score
  (`semantic_match["semantic_scores"]`) disagree by a wide margin on the same pillar
  (e.g., work experience) — this is a legitimate signal of either a bad extraction or a
  bad LLM judgment, not something to silently average away.

**Data-source integrity checks**:
- `evaluate_semantic_with_safety_net` actually raised (per its documented "fail
  explicitly on API error, never fabricate" contract) rather than silently returning a
  sanitized-but-empty result — confirm the error propagates instead of being swallowed
  anywhere upstream.

### 4.2 Output contract

Produce a `ValidationReport` with:
```
{
  "status": "PASS" | "PASS_WITH_WARNINGS" | "BLOCKED",
  "findings": [
    {"check": str, "severity": "BLOCKING"|"WARNING"|"INFO",
     "message": str, "evidence": {...}, "affected_pillar": str|null}
  ],
  "grounding_coverage": float  # fraction of extracted claims traced back to source text
}
```
`BLOCKED` should mean "do not show this score as-is" (e.g., ungrounded fabricated
metric driving a pillar score) and must propagate back to `run_evaluation.py` as a
non-zero-but-distinct exit condition, not silently swallowed into the normal output.

---

## 5. Phase 3 — Agentic Recommendation Engine

Build a new module, e.g. `recommendation_agent.py`, consumed only after validation
returns `PASS` or `PASS_WITH_WARNINGS`. This should genuinely be agentic — multiple
reasoning steps with a self-check, not one LLM call that free-associates advice.

### 5.1 Pipeline

1. **Attribute the gap.** For the given track, compute which pillar(s) contribute most
   to the distance between `overall_score` and the next verdict threshold up (the
   thresholds are already defined in `scorer_engine.py`: 58/70/80/90). Use
   `ROLE_WEIGHTS[track]` to rank pillars by (weight × headroom), not just by raw score,
   so recommendations target the highest-leverage fix, not just the lowest score.
2. **Ground each recommendation in evidence already computed**, don't regenerate from
   scratch:
   - Missing CPI / low CPI → cite `signals["cpi_status"]` directly.
   - Weak SCOPE articulation → cite the actual bullet text lacking quantification, not
     a generic "add more metrics" — pull from `structured_resume["Projects"]` /
     `["Work Experience"]` directly and point at specific bullets.
   - Weak branch match for the track → if and only if it's meaningfully fixable advice
     (mostly it isn't — branch is fixed), reframe as compensating-signal advice (e.g.
     "CORE_TECHNOM branch match is capped for your branch; PoR/coursework carry more
     relative weight for you — see below") rather than telling someone to change branch.
   - Missing/low PoR → check `por_tier == 8` case distinctly (§4.1): if it's a detection
     gap not a genuine absence, the recommendation agent must not tell a candidate who
     actually has strong PoR to "seek more leadership roles." This is exactly why the
     validation pass must run first and its findings must be passed into this agent's
     context.
   - Company/pedigree gaps → use `kg_adapter.get_pedigree_tier()` results, phrased per
     §2's `recruits_for` vs `pedigree_for` distinction: never suggest a candidate "apply
     to Jane Street for a campus role" (`PPO_DOMINANT`) as concrete actionable advice —
     that channel doesn't exist. Any company-shaped advice must pass through this check.
   - "What good looks like" calibration → pull 1–3 anonymized *pattern-level* exemplars
     from that track's `positive_spikes_registry` for the relevant pillar/section,
     but **never quote `evidence` text verbatim into candidate-facing output** and
     never surface `candidate_source`. Describe the pattern ("candidates scoring
     Outstanding here typically quantify pipeline throughput or latency deltas, not just
     name the tool stack") rather than reproducing another person's resume language.
3. **Self-critique pass.** Before finalizing, run a second pass (can be a second LLM
   call or a deterministic checklist, your choice, but must be explicit and inspectable)
   that rejects any recommendation which:
   - Contradicts a validation `BLOCKING`/`WARNING` finding from Phase 2.
   - Asks the candidate to fabricate or exaggerate ("just add a 30% improvement metric")
     — recommendations must be about better articulating real work, never about
     inventing numbers. This must be a hard rule, not a style preference.
   - Treats branch affinity or PoR-hierarchy detection as an eligibility gate rather
     than descriptive context, per §2.
   - Is generic filler that doesn't reference anything specific to this resume (if you
     can't point to the specific bullet/field it's about, drop it).
4. **Output** both a structured `recommendations.json` (pillar → ranked list of
   `{issue, evidence_ref, suggested_action, expected_impact}`) and a short human-readable
   markdown summary suitable for showing the candidate directly.

---

## 6. Orchestration & CLI

Extend `run_evaluation.py` (don't create a parallel entry point):

```
python run_evaluation.py resume.pdf --track SDE \
    --kg_export path/to/kg_export.json \
    --validate --recommend \
    --json_out results.json
```

- `--kg_export` should have a sensible default (build/refresh it once, cache to disk,
  reuse across runs — do not call `iitk_kg.py build` per resume evaluation) and a clear
  error message if missing/stale, not a silent fallback to the old hardcoded lists.
- `--validate` runs Phase 2 and, on `BLOCKED`, exits non-zero with the findings printed,
  without proceeding to scoring output as if nothing happened.
- `--recommend` runs Phase 3 and appends its output to the JSON result and prints the
  human-readable summary.
- Update `README.md`'s architecture section (currently documents 5 layers) to add the
  KG integration and the two new agentic layers as layers 6 and 7, keeping the existing
  doc's tone/format.

---

## 7. Acceptance criteria (definition of done)

- [ ] There is exactly one place in the codebase that defines company tiers, and it
      reads from the KG export, not from three disagreeing hardcoded lists.
- [ ] There is exactly one canonical track/role name mapping table, imported by every
      module that needs it (scorer, semantic matcher, KG adapter, CLI argparse).
- [ ] `semantic_signal_matcher.py` no longer does bare substring containment against a
      fixed keyword array as its primary matching strategy.
- [ ] Running the full pipeline on a sample resume with `--validate` produces a
      `ValidationReport` that would actually catch a deliberately-injected bad case (test
      this: hand-edit a `structured_resume` to include a fabricated company/metric not
      in the source PDF text, confirm it's flagged).
- [ ] Running with `--recommend` produces recommendations that (a) cite specific
      resume content, not generic advice, (b) never suggest fabricating metrics, (c)
      never suggest applying to a `PPO_DOMINANT` firm as a campus-recruiting action.
- [ ] `ROLE_WEIGHTS` sums to 1.0 for every track, enforced by a test, not just eyeballed.
- [ ] `README.md` is updated to describe the real, current architecture (7 layers).
- [ ] No PII or `candidate_source` values from the signal dictionaries leak into any
      candidate-facing output.

Write tests for the above, not just manual runs. Use the signal dictionaries' own
`positive_spikes_registry` entries as fixtures for calibration/regression testing of
the recommendation engine's "what does outstanding look like" logic, since no raw
sample resumes were provided — construct synthetic `structured_resume` JSON fixtures
from a few dictionary entries per track instead of inventing arbitrary test data.
