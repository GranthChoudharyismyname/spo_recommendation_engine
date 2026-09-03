/**
 * The contract with POST /api/evaluate.
 *
 * Fields are grouped by where they come from, because the UI labels them differently:
 *
 *   ENGINE   produced by scorer_engine.score_resume — the scores themselves.
 *   DERIVED  produced by the API adapter's rule layers. `derived` names the ruleset
 *            behind each one so the UI can say what generated it.
 */

export type TrackCode =
  | "ANALYST_AIML"
  | "CONSULT_PM"
  | "CORE_TECHNOM"
  | "QUANT"
  | "SDE";

export type Severity = "HIGH" | "IMPORTANT" | "POLISH";
export type VerdictBand =
  | "PRIME"
  | "OUTSTANDING"
  | "VERY_GOOD"
  | "BORDERLINE"
  | "HIGH_RISK";
export type EvaluationStatus = "COMPLETE" | "DEGRADED";
export type ComplianceStatus =
  | "COMPLIANT"
  | "REVIEW_REQUIRED"
  | "NON_COMPLIANT"
  | "UNAVAILABLE";
export type ScopeDimension = "SCALE" | "CONTEXT" | "OWN" | "PROOF" | "EDGE";

export interface TrackDefinition {
  code: TrackCode;
  label: string;
  short_label: string;
  description: string;
  project_pillar_label: string;
  kg_role: string;
  weights?: Array<{ pillar: string; weight: number }>;
}

/** Normalised 0..1 of the rendered page box, so the overlay is zoom-independent. */
export interface EvidenceRef {
  page: number;
  x: number;
  y: number;
  width: number;
  height: number;
  text: string;
  match: "exact" | "prefix";
}

export interface RecommendationDetail {
  scope_present?: ScopeDimension[];
  scope_missing?: ScopeDimension[];
  scope_covered?: number;
  scope_total?: number;
  engine_reasoning?: string | null;
  knowledge_base?: string;
}

export interface Recommendation {
  id: string;
  severity: Severity;
  title: string;
  rationale: string;
  action: string;
  section: string;
  pillar: string;
  evidence_text: string | null;
  evidence_refs: EvidenceRef[];
  /** The named rule that produced this item. Always shown; nothing here is model-authored. */
  source_rule: string;
  expected_impact: string;
  impact_points: number;
  pillar_weight: number;
  detail: RecommendationDetail;
}

export interface Pillar {
  key: string;
  label: string;
  score: number;
  max_score: number;
  tier: string | null;
  reasoning: string | null;
  weight: number;
  weighted_contribution: number;
  headroom_points: number;
  is_project_pillar: boolean;
}

export interface CompanyFitEntry {
  company: string;
  company_id: string;
  category: string;
  tier: number;
  tier_label: string;
  fit_score: number;
  fit_band: "Strong" | "Competitive" | "Stretch";
  rationale: string;
  recruiting_mode: string;
  source: string;
  /** From the built knowledge-graph export; null when only the seed is available. */
  iitk_presence?: string | null;
  presence_strength?: number | null;
  branch_affinity?: number | null;
}

export interface CompanyFit {
  available: boolean;
  reason?: string;
  entries: CompanyFitEntry[];
  model_version: string | null;
  disclosure: string;
  /** Stated once for the panel; the per-row rationale carries only the tier comparison. */
  driving_pillar?: string | null;
  kg_schema_version?: string;
  ppo_dominant_excluded?: number;
  campus_recruiter_pool?: number;
  shown?: number;
  branch_used?: string | null;
  kg_is_export?: boolean;
}

export interface ComplianceFinding {
  check: string;
  severity: "BLOCKING" | "WARNING" | "INFO";
  message: string;
  guideline: string;
  evidence: string | null;
  section: string | null;
}

export interface Compliance {
  status: ComplianceStatus;
  findings: ComplianceFinding[];
  counts: { blocking?: number; warning?: number; info?: number };
  source?: string;
}

export interface LayoutMetric {
  ACTUAL_VALUE: string | number;
  GUIDELINE_VALUE: string | number;
  DELTA: number;
  note?: string;
  detected_fonts?: string[];
  name_text?: string;
}

export interface ExtractedSignals {
  branch?: string;
  cpi?: number | null;
  cpi_status?: "VERIFIED" | "UNVERIFIED_MISSING";
  jee_adv_air?: number | null;
  cf_rating?: number | null;
  por_tier?: number;
  has_top_scholarship?: boolean;
  has_olympiad?: boolean;
  has_aea?: boolean;
  has_kvpy?: boolean;
  has_surge?: boolean;
  /** Your original 12-firm regex match, unchanged. */
  detected_analyst_firms?: string[];
  /** Additive KG resolution; does not affect any score. */
  kg_pedigree_firms?: Array<{
    organization: string;
    resolved_as: string;
    tier: number;
    edge_type: string;
    recruiting_mode: string;
  }>;
  kg_unverified_firms?: string[];
  /** "department_field" | "raw_text_fallback" | "undetected" */
  branch_source?: string;
  /** Quantified results, in the same shape the signal corpora use. */
  quantified_results?: QuantifiedResult[];
  quantified_results_summary?: QuantifiedResultsSummary;
}

/* ---- Phase 2: validation agent ---- */

export type ValidationStatus = "PASS" | "PASS_WITH_WARNINGS" | "NEEDS_REVIEW";

/** No severity withholds a result; they rank how much attention a finding deserves. */
export type FindingSeverity = "CRITICAL" | "WARNING" | "INFO";

export interface ValidationFinding {
  check: string;
  severity: FindingSeverity;
  message: string;
  evidence: Record<string, unknown>;
  affected_pillar: string | null;
}

export interface ValidationReport {
  status: ValidationStatus;
  findings: ValidationFinding[];
  /** Fraction of extracted claims traced back to the PDF text. Null when not audited. */
  grounding_coverage: number | null;
  claims_audited: number;
  counts: { blocking: number; critical?: number; warning: number; info: number };
  checks_run: string[];
  checks_failed: string[];
  llm_used: boolean;
  agent_version: string;
}

/* ---- Phase 3: recommendation agent ---- */

export interface AttributionPillar {
  pillar: string;
  score: number;
  weight: number;
  headroom_points: number;
  tier: string | null;
  reasoning: string | null;
}

export interface AgentRecommendation {
  id: string;
  severity: Severity;
  pillar: string;
  section: string;
  issue: string;
  evidence_ref: string;
  suggested_action: string;
  expected_impact: string;
  source_rule: string;
  critique?: string;
  rejected_by?: "code" | "critique";
  rejection_reason?: string;
}

export interface AgentRecommendations {
  agent_version: string;
  attribution: {
    overall_score: number;
    next_band: { threshold: number; label: string; points_needed: number } | null;
    ranked_pillars: AttributionPillar[];
    layout_headroom_points: number;
    total_available: number;
  };
  recommendations: AgentRecommendation[];
  /** Kept visible: an agent that silently drops its own output cannot be audited. */
  rejected: AgentRecommendation[];
  counts: {
    drafted: number;
    kept: number;
    rejected: number;
    rejected_by_code: number;
    rejected_by_critique: number;
  };
  blocked_companies_considered: string[];
  markdown: string;
}

/** Matches the corpora's `impact` shape: {metric, direction, value, unit}. */
export interface QuantifiedResult {
  metric: string | null;
  direction: "decrease" | "increase" | "top" | "achieved" | null;
  value: number;
  unit: string | null;
  /** The source bullet, so the figure can be traced back to the PDF. */
  evidence: string;
  section: string;
  entry: string;
}

export interface QuantifiedResultsSummary {
  total: number;
  by_section: Record<string, number>;
  quantified_bullets: number;
  total_bullets: number;
  /** Bullets stating a result vs. bullets describing activity — what SCOPE measures. */
  quantified_bullet_ratio: number;
  named_metrics: string[];
}

/** A deterministic floor that raised a pillar score, with the evidence behind it. */
export interface EvidenceAdjustment {
  pillar: string;
  floor: number;
  from: number;
  to: number;
  field: "work_experience" | "scope";
  reason: string;
  evidence: Record<string, unknown>;
}

export interface EvaluationWarning {
  code: string;
  message: string;
}

/** One component of the structural score, with what it cost. */
export interface StructuralComponent {
  key: string;
  label: string;
  /** This component on its own 0-100 scale. */
  sub_score: number;
  /** Its share of the structural score, 0-1. */
  weight: number;
  points_earned: number;
  points_available: number;
  points_lost: number;
  metric: LayoutMetric | null;
}

export interface StructuralBreakdown {
  total: number;
  components: StructuralComponent[];
  blank_document: boolean;
}

/** Layout read by the vision model; absent unless a VLM backend ran. */
export interface StructuralVisual {
  score: number;
  backend?: string;
  notes?: string[];
  [key: string]: unknown;
}

/** How large an employer is, for firms the recruiter graph does not carry. */
export interface CompanyProfile {
  name: string;
  band: string;
  label: string;
  note: string;
  source: string;
}

/** The three sections the problem statement names, assembled from existing findings. */
export interface ReportStrength {
  title: string;
  detail: string;
  evidence: string;
  pillar: string;
}

export interface ReportGap {
  title: string;
  detail: string;
  why: string;
  section: string | null;
  impact_points: number | null;
  source: string;
  blocking: boolean;
  evidence_refs?: EvidenceRef[];
}

export interface ReportFormattingFix {
  title: string;
  detail: string;
  fix: string;
  impact_points: number | null;
  source: string;
  evidence_refs: EvidenceRef[];
}

export interface DiagnosticReport {
  top_strengths: ReportStrength[];
  critical_missing: ReportGap[];
  formatting_fixes: ReportFormattingFix[];
}

export interface EvaluationResult {
  evaluation_status: EvaluationStatus;
  warnings: EvaluationWarning[];
  track: TrackDefinition;
  file: { name: string; size_bytes: number; page_count: number };

  /* ENGINE */
  overall_score: number;
  verdict: string;
  verdict_band: VerdictBand;
  content_score: number;
  structural_score: number;
  pillars: Pillar[];
  extracted_signals: ExtractedSignals;
  deterministic_scores: Record<string, number>;
  semantic_benchmarks: Record<string, unknown>;
  spo_layout_metrics: Record<string, LayoutMetric>;
  /** How the structural score decomposes. Empty for a blank or unreadable document. */
  structural_breakdown: StructuralBreakdown | null;
  structural_visual: StructuralVisual | null;
  /** Named report sections; null on an older payload. */
  report: DiagnosticReport | null;
  structured_resume: Record<string, unknown>;

  /* DERIVED */
  recommendations: Recommendation[];
  recommendation_summary: { high: number; important: number; polish: number; total: number };
  company_fit: CompanyFit;
  compliance: Compliance;
  validation: ValidationReport | null;
  /** Empty when the qualitative scores already cleared every floor. */
  evidence_adjustments: EvidenceAdjustment[];
  /** Present only in a fixture session; never set by the real API. */
  mockNotes?: string[];
  agent_recommendations: AgentRecommendations | null;
  unverified_companies: string[];
  /** Size band for each employer outside the recruiter graph, keyed by name. */
  company_profiles: Record<string, CompanyProfile>;
  derived: {
    recommendations: string;
    company_fit: string | null;
    compliance: string;
    evidence_refs: string;
    validation: string | null;
    agent_recommendations: string | null;
  };
  meta: {
    engine_version: string;
    model: string;
    generated_at: string;
    duration_ms: number;
    evidence_resolved: number;
    evidence_requested: number;
    is_mock: boolean;
    mock_note?: string;
  };
}

export interface ApiErrorBody {
  error: { code: string; message: string; [key: string]: unknown };
}

export interface HealthResponse {
  status: string;
  engine_version: string;
  capabilities: {
    gemini_configured: boolean;
    knowledge_graph: boolean;
    kg_schema_version: string | null;
    kg_company_count: number;
  };
  limits: { max_upload_bytes: number; accepted_mime_types: string[] };
  model: string;
}
