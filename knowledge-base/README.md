# Knowledge base

Source material the engine is derived from. Nothing here is imported at runtime — these
are the documents the rules were transcribed from, kept so any rule can be traced back to
its origin and re-checked when the source changes.

| Path | What it is | What consumes it |
| --- | --- | --- |
| `role-frameworks/*.txt` | Per-track evaluation frameworks: pillar definitions, tier bands, the SCOPE framework, and the red flags that dilute a resume on that track. | `backend/app/track_rules.py` transcribes the SCOPE patterns and the per-track dilution rules. Each rule records its `kb_section`, e.g. `sde.txt §3.1`. |
| `spo-resume-guidelines.pdf` | Students' Placement Office resume-making guidelines, 6 pages. | `backend/app/compliance.py` implements the submission rules that are pass/fail policy rather than a gradient. Each finding quotes its page. |
| `signal-corpora/*.zip` | Per-candidate extractions from real resumes: structured JSON, raw markdown, and labelled signals with SCOPE dimensions. | Calibration and manual review only. **Not loaded by any runtime code.** |

## Privacy

The signal corpora contain real candidate material, including names in some filenames.
They are inputs to rule design, not to evaluation:

- No runtime module reads `signal-corpora/`.
- `candidate_source` values and verbatim `evidence` strings are never surfaced to a
  candidate. The recommendation agent is given only pattern-level descriptions of what
  an outstanding signal looks like, never another person's resume language.
- `backend/app/recommendation_agent.py` trims the rule findings it passes into the model
  prompt to a fixed field allowlist, so corpus internals cannot reach the LLM.

If this repository is ever published, drop `signal-corpora/` first.
