# IITK Recruiter Knowledge Graph — build tool

Single-file CLI. Standard library only, Python 3.9+. Storage is SQLite by default
(one file, no server); the schema is plain SQL and ports to Postgres unchanged
apart from `AUTOINCREMENT`/`TEXT` idioms.

## Why SQLite / relational rather than a graph database

~80 campus recruiters, 5 roles, a handful of cycles. Every query the app needs is
one or two joins deep. A graph database adds an operational dependency and buys
nothing at this scale. Revisit only if production path queries exceed three hops.

## Files

| File | Purpose |
|---|---|
| `iitk_kg.py` | the CLI |
| `companies.seed.json` | 78 curated firms with aliases, **two separate edge types** (`recruits_for` / `pedigree_for`) and `recruiting_mode` |
| `institutions.seed.json` | 42 universities, research labs and fellowships — pedigree entities for signal tiering, **not** campus recruiters |
| `departments.seed.json` | 30 department codes + 24 programme codes, from the DOAA Courses of Study Sept-25 and Template Jan-25 pages |
| `dept_map.csv` | your `spo_dept_id` → branch mapping, with the code tables in its header |

## The branch layer

Branch mix per company is retained as a distinct signal from the role-level branch
gate. The gate ("quant wants CSE/MTH/EE/SDS") lives in the five frameworks and is
checked against the candidate's own branch. The mix ("this firm took 90% from one
department last cycle") is observed evidence that tells a candidate from elsewhere
something the gate does not.

`export` emits per company:

```json
"branch_mix": [{"branch": "ME", "program": "MT", "n": 6, "suppressed": false}],
"branch_concentration": 0.667
```

`branch_concentration` is the share taken by the single largest branch — the
"is this firm branch-biased?" number.

**Render it as history, never as a criterion.** "Hired from these branches last
cycle, n=…" is honest; "you are ineligible" is not, because a branch absent last
cycle is not a rule.

### UG only

PG cohorts are excluded at ingest. IITK roll numbers are 6 digits for UG and 9 for
PG, so the record's programme level is read from the roll number's **length**, after
which the gate discards the value — nothing identifying survives that line.

`--include-pg` keeps them if you ever need to. `dept_map.csv` therefore carries only
UG ids: all twelve rows are confirmed, covering the eight B.Tech branches and the four
BS programmes present in the data.

## The branch mapping is yours to author

`dept_map.csv` is the single source of truth for `spo_dept_id -> branch`. Nothing
else writes to it. Fill rows as `spo_dept_id,dept_code,program_code` using the code
tables printed in the file header; blank rows are skipped, so partial mappings work.

To read the ids: open the SPO site, filter by branch, and match the cohort size
against the `# cohort=` hint on each row. The template is sorted large-first, so the
top ~15 rows cover most of the placement population.

Validate any time:

```bash
python3 iitk_kg.py deptmap --check
```

It reports coverage as a share of placed students, and catches:

* unknown department or programme codes (row skipped, not silently written)
* the same branch+programme mapped to two different ids
* ids mapped that never appear in the SPO payload

`report` then prints the top branches by placements, so you can eyeball whether the
mapping looks right before trusting it.

### Do not infer ids from patterns

Two shortcuts were tried and both fail. **Cohort size:** id 6 has the second-largest
cohort and a tech-heavy hiring mix, so guessing "CSE" is natural — and wrong.
**Alphabetical order:** ordering by acronym predicts 7=ME/8=MSE, ordering by full
name predicts 3=CHE/4=CE; both are the reverse of what the ids actually are. Every
ordering that fits most ids breaks on the near-alphabetical pairs (CE/CHE, ME/MSE),
which is exactly where a wrong label is hardest to notice.

Read the ids off the SPO site instead. It takes a few minutes and it is correct.

## Two edge types — do not collapse them

`recruits_for` means the firm hires for that role at IITK. It drives the campus panel.

`pedigree_for` means an internship **at** that firm is a positive signal when **applying**
for that role. It scores work experience and must never surface as a campus recommendation.

The frameworks mix these freely. `quant.txt` names Swiggy, Flipkart, Razorpay and Sprinklr
under Pillar 5 Work Experience — "Core Backend / HPC / Algorithms engineering at top tech
firms" is a Very Good signal *for a quant applicant*. It does not mean Swiggy runs a quant
desk. Same for Google Systems, Microsoft Azure, Databricks, Rubrik, Meta and Uber Core Infra.
Collapsing the two edges recommends Swiggy to a quant candidate, which is wrong.

Current split: QUANT has 18 recruiters and 10 pedigree-only firms. The other four roles are
recruits-only, because their frameworks enumerate campus recruiters directly in the header.

## Quant will look empty, and that is correct

16 firms are marked `PPO_DOMINANT` — HFTs and prop shops hire almost entirely through
intern-to-PPO conversion, so they barely appear in placement offer data. `report` lists them
explicitly. The campus panel must state that these firms recruit via the internship cycle
rather than rendering an empty list, or a quant candidate will read absence as "they do not
come to IITK".

## Run it

```bash
python3 iitk_kg.py build
```

That is the whole thing: schema, curated registry, fetch, privacy gate, entity
resolution, role classification, aggregation, export. It prints what it built and
what optional curation remains.

Two flags worth knowing:

```bash
python3 iitk_kg.py build --file raw/stats.json    # use a local payload, skip the fetch
python3 iitk_kg.py build --purge-source           # delete the staging file after ingest
```

`build` is idempotent — re-run it after editing `companies.seed.json` and it
rebuilds from scratch.

### The other subcommands are optional

`init`, `seed`, `fetch`, `ingest` are the individual stages, useful if you want to
re-ingest a new cycle without re-seeding. `report`, `review`, `classify`, `export`
are the curation and inspection tools. For a one-time build
you need none of them except `report` to look at the result.

## Curated does not mean "recruits at IITK"

The five role frameworks enumerate **domain leaders globally** — `quant.txt` opens with
Jane Street, Citadel, Jump, Optiver and so on. That is not a claim that each recruits on
campus, and the seed does not verify it.

Every exported company therefore carries `iitk_presence`:

| Value | Meaning | Safe to recommend? |
|---|---|---|
| `observed_at_iitk` | appeared in SPO placement data | yes |
| `ppo_only_expected` | PPO-dominant firm, legitimately absent from offer data | yes, with the PPO caveat |
| `not_observed_at_iitk` | named in a framework, never seen here | **no** — unverified |

`report` lists the unverified ones so you can confirm against SPO and either promote them
or drop them from the seed. Until confirmed, keep them out of the campus panel: telling a
candidate to target a firm that never visits is worse than showing a shorter list.

Note that `not_observed_at_iitk` firms are still useful as `pedigree_for` entries — an
Amazon internship is a strong signal whether or not Amazon recruits here.

## The export carries signals, not statistics

`export` defaults to `--mode signals`. Nothing that leaves the graph is a count, so
the dashboard has no placement numbers to render and nothing needs k-anonymity
suppression.

| Field | Meaning | Range |
|---|---|---|
| `observed_recruiting` | this firm recruited at IITK for this role | bool |
| `presence_strength` | hiring volume relative to the largest recruiter *in that role* | 0–1 |
| `ppo_orientation` | share of intake that came via PPO conversion | 0–1 |
| `evidence_strength` | how much the observation should be trusted, `n/(n+8)` | 0–1 |
| `branch_affinity[]` | share of this firm's intake from each branch | 0–1 each |
| `branch_concentration` | affinity of the single largest branch | 0–1 |
| `branch_evidence_strength` | trust weight for the branch mix | 0–1 |

**Multiply `evidence_strength` into anything derived from the observed block.** It is
what stops a single hire behaving like a trend. Squarepoint in the test data has
`presence_strength 1.0` — it is the only quant firm present, so it *is* the maximum —
but `evidence_strength 0.111`, because that maximum rests on one hire. The product,
0.111, is the honest weight.

Render these qualitatively. `branch_concentration 0.9` becomes "hires almost entirely
from one branch"; `ppo_orientation 0.8` becomes "mostly converts interns — target the
internship cycle". Never surface the number itself.

`--mode raw` adds counts back for debugging and curation. Do not ship it to a client.

## Privacy contract

`name`, `email` and `roll_no` are removed inside the parser, before resolution or
classification, so they never reach storage or logs. No per-student row exists in the
database — records are counted into aggregates and the parsed list is discarded.

`fetch` writes the raw payload (which does contain identifiers) to a staging path.
Use `--purge-source` on ingest and keep `raw/` out of version control.

The default export emits shares, not counts, so nothing disclosive leaves the graph.


## What this graph does and does not contain

Derived from the SPO endpoint: presence, hiring volume, PPO share, profile titles.

**Not derivable and never inferred from it:** CPI cutoffs, stipends, application
denominators, and which resume signals a company weights. Gates stay curated;
`values` edges come from job-description mining and curation. Hiring volume is not
a tier proxy — it inverts at the top, where the most selective firms hire one or two.

## Curation loop

Three queues, all surfaced by `unmapped` and `review`:

1. **Entity resolution** — pairs scoring 0.78–0.93 are held for a human. Below 0.78
   a new observed company is created; at or above 0.93 it auto-merges. Decisions are
   stored as permanent aliases, so the same ambiguity is never adjudicated twice.
2. **Tier assignment** — companies present in the data but absent from all five
   frameworks land as `TIER_UNKNOWN` and appear in `unmapped`, ordered by hires.
3. **Profile classification** — ambiguous strings ("Manager -1", "Analyst - C09",
   bare punctuation) stay `UNCLASSIFIED` rather than being guessed. Override with
   `classify --set "Analyst - C09=ANALYST"`.

## Curation, all optional

Three queues surfaced by `unmapped` and `review`. Skipping them costs coverage, not
correctness — unclassified openings are excluded from role counts rather than
misfiled, and untiered firms show as TIER_UNKNOWN rather than being guessed.

---

## What the database contains

SQLite, one file. 16 tables and 2 views, in four layers.

```
CURATED (from your five role frameworks + DOAA)   — stable, you edit these
   company · company_alias · company_role_tier · desk
   institution · institution_alias
   department · program

MAPPING (you author)                              — the join SPO does not publish
   spo_dept_map

OBSERVED (from the SPO payload)                   — aggregates only, never per-student
   role_opening · placement_agg · department_cycle_stats

OPERATIONAL (pipeline bookkeeping)
   profile_classification · resolution_review · ingest_run · meta
```

---

## Curated layer

### `company` — 79 rows in a fresh build
`id, display_name, canonical_key, category, hq_region, origin, recruiting_mode, note, created_at`

One row per firm. `origin` is `curated` (named in a framework) or `observed` (appeared
in SPO data only). `recruiting_mode` is `PPO_DOMINANT`, `CAMPUS_OFFER` or `BOTH` —
16 firms are PPO-dominant, which is why quant looks sparse in offer data.
`canonical_key` is the aggressively normalized form used for matching.

### `company_alias` — ~146 rows
`company_id, alias, alias_key, source`

Every surface form that resolves to a company. Holds the framework name, the SPO
spellings, legal-suffix variants, and manual review decisions. `source` records which.
This is what collapses four Accenture strings, `NVIDIA ` with a trailing space, and
`Eternal Limited(Formerly known as Zomato Limited)` onto single nodes.

### `company_role_tier` — 118 rows
`company_id, role, edge_type, tier, source`

**The most important table.** `edge_type` is either:

* `recruits` — this firm hires for this role at IITK; drives recommendations
* `pedigree` — an internship *here* is a signal when *applying* for this role; scores
  work experience and must never surface as a recommendation

That split is what keeps Swiggy out of quant recommendations while still crediting a
Swiggy backend internship on a quant resume. `tier` 1–4, NULL means TIER_UNKNOWN.
`source` traces each row to the framework that asserted it.

### `desk` — practice/unit splits
`id, company_id, name`

Accenture Data-AI vs Operations vs Strategy hire different profiles from different
branches. One company, several desks.

### `institution` / `institution_alias` — 42 + 82 rows
`id, display_name, kind, tier, region, roles`

Universities, research labs and fellowships. **Not recruiters.** They tier research and
internship signals during scoring and are deliberately in a separate table so they
cannot leak into job recommendations.

### `department` — 30 rows · `program` — 24 rows
`code, name, kind, source` / `code, name, level`

IITK vocabulary from the DOAA Courses of Study Sept-25 and Template Jan-25 pages, plus
legacy units. `source` records which page each came from.

---

## Mapping layer

### `spo_dept_map` — 79 rows, 12 filled
`spo_dept_id, dept_code, program_code, source`

Your hand-authored `spo_dept_id → branch` mapping. The 12 filled rows were measured,
not guessed, and cover all eight B.Tech branches. Unmapped ids still aggregate; they
just render as `UNMAPPED` in branch affinity.

---

## Observed layer

### `role_opening`
`id, company_id, desk_id, role, profile_raw, cycle`

One row per (company, job title, cycle). `role` is one of the five, or `UNCLASSIFIED`
when the title is genuinely ambiguous (`Manager -1`, `Analyst - C09`, a bare `.`).
Unclassified rows are excluded from role counts rather than misfiled.

### `placement_agg` — the only table holding SPO outcome data
`opening_id, spo_dept_id, cycle, n_recruited, n_ppo, n_dual_major`

**Aggregate counts only.** One row per (opening, branch, cycle). No student row exists
anywhere in the database — records are counted during ingest and the parsed list is
discarded. Names, emails and roll numbers are dropped in the parser, before resolution
or classification.

### `department_cycle_stats`
`spo_dept_id, cycle, total, pre_offer, recruited`

Cohort size and placement rate per branch per cycle. Denominators for normalization.

---

## Operational layer

`profile_classification` — job title → role, with method (`rule`, `rule_priority`,
`manual`) and confidence. Your `classify --set` overrides land here and persist.

`resolution_review` — company-name pairs scoring 0.78–0.93, held for a human. Below
0.78 creates a new company; at or above 0.93 auto-merges. This is what stopped ICICI
Bank silently merging into Citi Bank at 0.84.

`ingest_run` — source URL, sha256, cycle, record counts, timestamp. Provenance per run.

`meta` — schema version, k-anonymity threshold.

---

## Views

`v_company_role_presence` — hiring volume and PPO split per company × role × cycle.

`v_company_branch_mix` — branch distribution per company × role, with a `suppressed`
flag on cells below k=5.

Both carry raw counts and are for direct SQL inspection. They are not what the app
consumes — `export` converts everything to shares first.

---

## Role × branch signals

Yes, derivable — `placement_agg` joins to `role_opening` (role) and `spo_dept_map`
(branch), so both directions come out. `export` emits them as top-level blocks.

**`role_branch_signals`** — who gets hired for a role:

```json
"SDE":  {"branch_affinity": [{"branch":"CSE","affinity":0.652},
                             {"branch":"EE","affinity":0.348}],
         "branch_concentration": 0.652, "n_branches": 2,
         "evidence_strength": 0.479}
```

**`branch_role_signals`** — where a branch actually goes. Often the more useful
direction for a candidate:

```json
"CSE":  {"role_affinity": [{"role":"SDE","affinity":0.652},
                           {"role":"ANALYST","affinity":0.261},
                           {"role":"QUANT","affinity":0.087}],
         "dominant_role": "SDE", "evidence_strength": 0.479}
```

Both carry `evidence_strength` at `n/(n+25)` — a stiffer shrinkage than the
per-company figure, because a role-level base rate needs more support before it means
anything.

### The caveat that matters

These are conditioned on **placement offers only**. Roles that hire mainly through
intern-to-PPO conversion — quant above all — are structurally under-represented. In a
test build QUANT came out `CSE: 1.0, evidence_strength 0.074`: that is two hires, not
a finding, and it says nothing about whether quant firms consider other branches.

So gate every use on `evidence_strength`, and treat the output as observed history,
never as eligibility. "Most CSE placements last cycle were SDE" is fair. "CSE is the
branch for quant" is not supported by this data and would discourage exactly the
candidates the frameworks say are eligible.

---

## What is deliberately absent

| Not stored | Why |
|---|---|
| Any per-student row | Aggregates only, by construction |
| Names, emails, roll numbers | Dropped in the parser, never written |
| CPI cutoffs, eligibility gates | Not in the SPO data; would be a fabrication |
| `values` preference edges | Need JD mining or outcome labels, not outcome counts |
| Stipend / CTC | Not published in the endpoint |
| Shortlist or application denominators | Only outcomes are published, so no conversion rates |

The last three are the integrity boundary. Everything the database holds is counting;
anything past that line is knowledge this source does not contain.
