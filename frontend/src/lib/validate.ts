/**
 * Runtime validation of the evaluation response.
 *
 * A typed interface is a compile-time promise about a network payload, which is no
 * promise at all. Every field the UI renders is checked here before it reaches a
 * component, and a response that fails is reported as malformed rather than rendered
 * with holes in it.
 */

import type {
  StructuralComponent,
  AgentRecommendation,
  AgentRecommendations,
  Compliance,
  CompanyFit,
  EvaluationResult,
  Pillar,
  Recommendation,
  Severity,
  EvidenceAdjustment,
  ValidationReport,
  ValidationStatus,
  VerdictBand,
} from "./types";

export class MalformedResponseError extends Error {
  readonly problems: string[];
  constructor(problems: string[]) {
    super(`The evaluation response was malformed: ${problems.join("; ")}`);
    this.name = "MalformedResponseError";
    this.problems = problems;
  }
}

const SEVERITIES: Severity[] = ["HIGH", "IMPORTANT", "POLISH"];
const BANDS: VerdictBand[] = [
  "PRIME",
  "OUTSTANDING",
  "VERY_GOOD",
  "BORDERLINE",
  "HIGH_RISK",
];

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/**
 * The API is trusted but versioned; a breakdown from an older build may be missing,
 * so every component is checked before it reaches the panel.
 */
function parseStructuralBreakdown(
  raw: unknown,
): EvaluationResult["structural_breakdown"] {
  if (!isRecord(raw) || !Array.isArray(raw.components)) return null;
  const components = raw.components.filter(
    (c): c is StructuralComponent =>
      isRecord(c) &&
      typeof c.key === "string" &&
      typeof c.label === "string" &&
      typeof c.sub_score === "number" &&
      typeof c.weight === "number" &&
      typeof c.points_lost === "number",
  );
  if (components.length === 0) return null;
  return {
    total: typeof raw.total === "number" ? raw.total : 0,
    components,
    blank_document: raw.blank_document === true,
  };
}

const isScore = (v: unknown, max: number): v is number =>
  typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= max;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function validatePillars(raw: unknown, problems: string[]): Pillar[] {
  if (!Array.isArray(raw)) {
    problems.push("`pillars` is not an array");
    return [];
  }
  const out: Pillar[] = [];
  raw.forEach((entry, index) => {
    if (!isRecord(entry) || typeof entry.key !== "string") {
      problems.push(`pillars[${index}] has no key`);
      return;
    }
    if (!isScore(entry.score, 20)) {
      problems.push(`pillars[${index}] (${entry.key}) has an out-of-range score`);
      return;
    }
    out.push({
      key: entry.key,
      label: typeof entry.label === "string" ? entry.label : entry.key,
      score: entry.score,
      max_score: isScore(entry.max_score, 100) ? entry.max_score : 20,
      tier: typeof entry.tier === "string" ? entry.tier : null,
      reasoning: typeof entry.reasoning === "string" ? entry.reasoning : null,
      weight: typeof entry.weight === "number" ? clamp(entry.weight, 0, 1) : 0,
      weighted_contribution:
        typeof entry.weighted_contribution === "number" ? entry.weighted_contribution : 0,
      headroom_points:
        typeof entry.headroom_points === "number" ? entry.headroom_points : 0,
      is_project_pillar: entry.is_project_pillar === true,
    });
  });
  return out;
}

function validateRecommendations(raw: unknown, problems: string[]): Recommendation[] {
  if (!Array.isArray(raw)) {
    problems.push("`recommendations` is not an array");
    return [];
  }
  const seen = new Set<string>();
  const out: Recommendation[] = [];
  raw.forEach((entry, index) => {
    if (!isRecord(entry)) return;
    const { id, severity, title } = entry;
    if (typeof id !== "string" || !id) {
      problems.push(`recommendations[${index}] has no id`);
      return;
    }
    if (seen.has(id)) {
      // Cards and PDF highlights are keyed by id; a duplicate would make the
      // hover-to-highlight mapping non-deterministic.
      problems.push(`recommendations[${index}] repeats id "${id}"`);
      return;
    }
    if (!SEVERITIES.includes(severity as Severity)) {
      problems.push(`recommendations[${index}] has severity "${String(severity)}"`);
      return;
    }
    if (typeof title !== "string" || !title) {
      problems.push(`recommendations[${index}] has no title`);
      return;
    }
    seen.add(id);

    const refs = Array.isArray(entry.evidence_refs)
      ? entry.evidence_refs.filter(
          (r): r is Recommendation["evidence_refs"][number] =>
            isRecord(r) &&
            typeof r.page === "number" &&
            r.page >= 1 &&
            ["x", "y", "width", "height"].every(
              (k) => typeof r[k] === "number" && (r[k] as number) >= -0.01 && (r[k] as number) <= 1.01,
            ),
        )
      : [];

    out.push({
      id,
      severity: severity as Severity,
      title,
      rationale: typeof entry.rationale === "string" ? entry.rationale : "",
      action: typeof entry.action === "string" ? entry.action : "",
      section: typeof entry.section === "string" ? entry.section : "",
      pillar: typeof entry.pillar === "string" ? entry.pillar : "",
      evidence_text: typeof entry.evidence_text === "string" ? entry.evidence_text : null,
      evidence_refs: refs,
      source_rule: typeof entry.source_rule === "string" ? entry.source_rule : "UNSPECIFIED_RULE",
      expected_impact: typeof entry.expected_impact === "string" ? entry.expected_impact : "",
      impact_points: typeof entry.impact_points === "number" ? entry.impact_points : 0,
      pillar_weight: typeof entry.pillar_weight === "number" ? entry.pillar_weight : 0,
      detail: isRecord(entry.detail) ? (entry.detail as Recommendation["detail"]) : {},
    });
  });
  return out;
}

function validateCompanyFit(raw: unknown): CompanyFit {
  if (!isRecord(raw)) {
    return {
      available: false,
      reason: "No shortlist-fit block was returned.",
      entries: [],
      model_version: null,
      disclosure: "",
    };
  }
  const entries = Array.isArray(raw.entries)
    ? raw.entries.filter(
        (e): e is CompanyFit["entries"][number] =>
          isRecord(e) && typeof e.company === "string" && isScore(e.fit_score, 100),
      )
    : [];
  return {
    available: raw.available === true && entries.length > 0,
    reason: typeof raw.reason === "string" ? raw.reason : undefined,
    entries,
    model_version: typeof raw.model_version === "string" ? raw.model_version : null,
    disclosure: typeof raw.disclosure === "string" ? raw.disclosure : "",
    driving_pillar: typeof raw.driving_pillar === "string" ? raw.driving_pillar : null,
    kg_schema_version:
      typeof raw.kg_schema_version === "string" ? raw.kg_schema_version : undefined,
    ppo_dominant_excluded:
      typeof raw.ppo_dominant_excluded === "number" ? raw.ppo_dominant_excluded : undefined,
    campus_recruiter_pool:
      typeof raw.campus_recruiter_pool === "number" ? raw.campus_recruiter_pool : undefined,
    shown: typeof raw.shown === "number" ? raw.shown : undefined,
    branch_used: typeof raw.branch_used === "string" ? raw.branch_used : null,
    kg_is_export: raw.kg_is_export === true,
  };
}

function validateValidationReport(raw: unknown): ValidationReport | null {
  if (!isRecord(raw)) return null;
  const status = raw.status;
  const findings = Array.isArray(raw.findings)
    ? raw.findings.filter(
        (f): f is ValidationReport["findings"][number] =>
          isRecord(f) && typeof f.check === "string" && typeof f.message === "string",
      )
    : [];
  const counts = isRecord(raw.counts) ? raw.counts : {};
  const coverage = raw.grounding_coverage;
  return {
    status:
      status === "PASS" || status === "PASS_WITH_WARNINGS" || status === "NEEDS_REVIEW"
        ? (status as ValidationStatus)
        // The engine previously emitted BLOCKED; map it rather than mislabelling.
        : status === "BLOCKED"
          ? "NEEDS_REVIEW"
          : "PASS_WITH_WARNINGS",
    findings,
    grounding_coverage:
      typeof coverage === "number" && coverage >= 0 && coverage <= 1 ? coverage : null,
    claims_audited: typeof raw.claims_audited === "number" ? raw.claims_audited : 0,
    counts: {
      blocking: typeof counts.blocking === "number" ? counts.blocking : 0,
      warning: typeof counts.warning === "number" ? counts.warning : 0,
      info: typeof counts.info === "number" ? counts.info : 0,
    },
    checks_run: Array.isArray(raw.checks_run)
      ? raw.checks_run.filter((c): c is string => typeof c === "string")
      : [],
    checks_failed: Array.isArray(raw.checks_failed)
      ? raw.checks_failed.filter((c): c is string => typeof c === "string")
      : [],
    llm_used: raw.llm_used === true,
    agent_version: typeof raw.agent_version === "string" ? raw.agent_version : "unknown",
  };
}

function validateAgentRecommendation(raw: unknown): AgentRecommendation | null {
  if (!isRecord(raw)) return null;
  const severity = SEVERITIES.includes(raw.severity as Severity)
    ? (raw.severity as Severity)
    : "IMPORTANT";
  const issue = typeof raw.issue === "string" ? raw.issue : "";
  if (!issue) return null;
  return {
    id: typeof raw.id === "string" && raw.id ? raw.id : `agent-${issue.slice(0, 24)}`,
    severity,
    pillar: typeof raw.pillar === "string" ? raw.pillar : "",
    section: typeof raw.section === "string" ? raw.section : "",
    issue,
    evidence_ref: typeof raw.evidence_ref === "string" ? raw.evidence_ref : "",
    suggested_action: typeof raw.suggested_action === "string" ? raw.suggested_action : "",
    expected_impact: typeof raw.expected_impact === "string" ? raw.expected_impact : "",
    source_rule: typeof raw.source_rule === "string" ? raw.source_rule : "AGENT_DERIVED",
    critique: typeof raw.critique === "string" ? raw.critique : undefined,
    rejected_by:
      raw.rejected_by === "code" || raw.rejected_by === "critique" ? raw.rejected_by : undefined,
    rejection_reason:
      typeof raw.rejection_reason === "string" ? raw.rejection_reason : undefined,
  };
}

function validateAgentRecommendations(raw: unknown): AgentRecommendations | null {
  if (!isRecord(raw)) return null;
  const attribution = isRecord(raw.attribution) ? raw.attribution : {};
  const nextBand = isRecord(attribution.next_band) ? attribution.next_band : null;
  const counts = isRecord(raw.counts) ? raw.counts : {};
  const num = (v: unknown, d = 0) => (typeof v === "number" ? v : d);

  const list = (v: unknown): AgentRecommendation[] =>
    Array.isArray(v)
      ? v.map(validateAgentRecommendation).filter((r): r is AgentRecommendation => r !== null)
      : [];

  return {
    agent_version: typeof raw.agent_version === "string" ? raw.agent_version : "unknown",
    attribution: {
      overall_score: num(attribution.overall_score),
      next_band:
        nextBand && typeof nextBand.label === "string"
          ? {
              threshold: num(nextBand.threshold),
              label: nextBand.label,
              points_needed: num(nextBand.points_needed),
            }
          : null,
      ranked_pillars: Array.isArray(attribution.ranked_pillars)
        ? attribution.ranked_pillars
            .filter((p): p is Record<string, unknown> => isRecord(p) && typeof p.pillar === "string")
            .map((p) => ({
              pillar: p.pillar as string,
              score: num(p.score),
              weight: num(p.weight),
              headroom_points: num(p.headroom_points),
              tier: typeof p.tier === "string" ? p.tier : null,
              reasoning: typeof p.reasoning === "string" ? p.reasoning : null,
            }))
        : [],
      layout_headroom_points: num(attribution.layout_headroom_points),
      total_available: num(attribution.total_available),
    },
    recommendations: list(raw.recommendations),
    rejected: list(raw.rejected),
    counts: {
      drafted: num(counts.drafted),
      kept: num(counts.kept),
      rejected: num(counts.rejected),
      rejected_by_code: num(counts.rejected_by_code),
      rejected_by_critique: num(counts.rejected_by_critique),
    },
    blocked_companies_considered: Array.isArray(raw.blocked_companies_considered)
      ? raw.blocked_companies_considered.filter((c): c is string => typeof c === "string")
      : [],
    markdown: typeof raw.markdown === "string" ? raw.markdown : "",
  };
}

function validateCompliance(raw: unknown): Compliance {
  if (!isRecord(raw)) {
    return { status: "UNAVAILABLE", findings: [], counts: {} };
  }
  const findings = Array.isArray(raw.findings)
    ? raw.findings.filter(
        (f): f is Compliance["findings"][number] =>
          isRecord(f) && typeof f.check === "string" && typeof f.message === "string",
      )
    : [];
  const status = raw.status;
  return {
    status:
      status === "COMPLIANT" ||
      status === "REVIEW_REQUIRED" ||
      status === "NON_COMPLIANT"
        ? status
        : "UNAVAILABLE",
    findings,
    counts: isRecord(raw.counts) ? (raw.counts as Compliance["counts"]) : {},
    source: typeof raw.source === "string" ? raw.source : undefined,
  };
}

/** Throws MalformedResponseError when a field the dashboard depends on is unusable. */
export function validateEvaluation(raw: unknown): EvaluationResult {
  const problems: string[] = [];
  if (!isRecord(raw)) throw new MalformedResponseError(["the response was not an object"]);

  if (!isScore(raw.overall_score, 100)) problems.push("`overall_score` is not 0-100");
  if (!isScore(raw.content_score, 100)) problems.push("`content_score` is not 0-100");
  if (!isScore(raw.structural_score, 100)) problems.push("`structural_score` is not 0-100");
  if (typeof raw.verdict !== "string" || !raw.verdict) problems.push("`verdict` is missing");
  if (!isRecord(raw.track) || typeof raw.track.code !== "string") {
    problems.push("`track` is missing");
  }

  const pillars = validatePillars(raw.pillars, problems);
  if (pillars.length === 0) problems.push("no usable pillars were returned");

  // These four are fatal: the dashboard's headline cannot be rendered without them.
  if (problems.length > 0) throw new MalformedResponseError(problems);

  const recommendations = validateRecommendations(raw.recommendations, problems);
  const summary = isRecord(raw.recommendation_summary)
    ? raw.recommendation_summary
    : {};

  const band = BANDS.includes(raw.verdict_band as VerdictBand)
    ? (raw.verdict_band as VerdictBand)
    : "HIGH_RISK";

  const file = isRecord(raw.file) ? raw.file : {};
  const meta = isRecord(raw.meta) ? raw.meta : {};
  const derived = isRecord(raw.derived) ? raw.derived : {};

  return {
    evaluation_status:
      raw.evaluation_status === "DEGRADED" || problems.length > 0 ? "DEGRADED" : "COMPLETE",
    warnings: [
      ...(Array.isArray(raw.warnings)
        ? raw.warnings.filter(
            (w): w is { code: string; message: string } =>
              isRecord(w) && typeof w.message === "string",
          )
        : []),
      // Recoverable validation problems become visible warnings rather than silence.
      ...problems.map((p) => ({ code: "RESPONSE_PARTIAL", message: p })),
    ],
    track: raw.track as EvaluationResult["track"],
    file: {
      name: typeof file.name === "string" ? file.name : "resume.pdf",
      size_bytes: typeof file.size_bytes === "number" ? file.size_bytes : 0,
      page_count: typeof file.page_count === "number" ? file.page_count : 0,
    },
    overall_score: raw.overall_score as number,
    verdict: raw.verdict as string,
    verdict_band: band,
    content_score: raw.content_score as number,
    structural_score: raw.structural_score as number,
    pillars,
    extracted_signals: isRecord(raw.extracted_signals) ? raw.extracted_signals : {},
    deterministic_scores: isRecord(raw.deterministic_scores)
      ? (raw.deterministic_scores as Record<string, number>)
      : {},
    semantic_benchmarks: isRecord(raw.semantic_benchmarks) ? raw.semantic_benchmarks : {},
    spo_layout_metrics: isRecord(raw.spo_layout_metrics)
      ? (raw.spo_layout_metrics as EvaluationResult["spo_layout_metrics"])
      : {},
    structural_breakdown: parseStructuralBreakdown(raw.structural_breakdown),
    structural_visual: isRecord(raw.structural_visual)
      ? (raw.structural_visual as EvaluationResult["structural_visual"])
      : null,
    report: isRecord(raw.report)
      ? {
          top_strengths: Array.isArray(raw.report.top_strengths) ? raw.report.top_strengths : [],
          critical_missing: Array.isArray(raw.report.critical_missing) ? raw.report.critical_missing : [],
          formatting_fixes: Array.isArray(raw.report.formatting_fixes) ? raw.report.formatting_fixes : [],
        } as EvaluationResult["report"]
      : null,
    structured_resume: isRecord(raw.structured_resume) ? raw.structured_resume : {},
    recommendations,
    recommendation_summary: {
      high: typeof summary.high === "number" ? summary.high : countBy(recommendations, "HIGH"),
      important:
        typeof summary.important === "number"
          ? summary.important
          : countBy(recommendations, "IMPORTANT"),
      polish:
        typeof summary.polish === "number" ? summary.polish : countBy(recommendations, "POLISH"),
      total: recommendations.length,
    },
    company_fit: validateCompanyFit(raw.company_fit),
    compliance: validateCompliance(raw.compliance),
    validation: validateValidationReport(raw.validation),
    evidence_adjustments: Array.isArray(raw.evidence_adjustments)
      ? raw.evidence_adjustments.filter(
          (a): a is EvidenceAdjustment =>
            isRecord(a) &&
            typeof a.pillar === "string" &&
            typeof a.from === "number" &&
            typeof a.to === "number" &&
            // A floor that did not raise the score should never have been recorded.
            a.to > a.from,
        )
      : [],
    agent_recommendations: validateAgentRecommendations(raw.agent_recommendations),
    company_profiles: isRecord(raw.company_profiles)
      ? (raw.company_profiles as EvaluationResult["company_profiles"])
      : {},
    unverified_companies: Array.isArray(raw.unverified_companies)
      ? raw.unverified_companies.filter((c): c is string => typeof c === "string")
      : [],
    derived: {
      recommendations:
        typeof derived.recommendations === "string" ? derived.recommendations : "unknown",
      company_fit: typeof derived.company_fit === "string" ? derived.company_fit : null,
      compliance: typeof derived.compliance === "string" ? derived.compliance : "unknown",
      evidence_refs:
        typeof derived.evidence_refs === "string" ? derived.evidence_refs : "unknown",
      validation: typeof derived.validation === "string" ? derived.validation : null,
      agent_recommendations:
        typeof derived.agent_recommendations === "string" ? derived.agent_recommendations : null,
    },
    mockNotes: Array.isArray(raw.mockNotes)
      ? raw.mockNotes.filter((n): n is string => typeof n === "string")
      : undefined,
    meta: {
      engine_version: typeof meta.engine_version === "string" ? meta.engine_version : "unknown",
      model: typeof meta.model === "string" ? meta.model : "unknown",
      generated_at:
        typeof meta.generated_at === "string" ? meta.generated_at : new Date().toISOString(),
      duration_ms: typeof meta.duration_ms === "number" ? meta.duration_ms : 0,
      evidence_resolved: typeof meta.evidence_resolved === "number" ? meta.evidence_resolved : 0,
      evidence_requested:
        typeof meta.evidence_requested === "number" ? meta.evidence_requested : 0,
      is_mock: meta.is_mock === true,
      mock_note: typeof meta.mock_note === "string" ? meta.mock_note : undefined,
    },
  };
}

function countBy(recs: Recommendation[], severity: Severity): number {
  return recs.filter((r) => r.severity === severity).length;
}
