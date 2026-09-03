import type { Severity, VerdictBand } from "./types";

export const SEVERITY_LABEL: Record<Severity, string> = {
  HIGH: "High priority",
  IMPORTANT: "Important",
  POLISH: "Polish",
};

/** The counters above the recommendation list. Order is fixed. */
export const SEVERITY_ORDER: Severity[] = ["HIGH", "IMPORTANT", "POLISH"];

export const BAND_LABEL: Record<VerdictBand, string> = {
  PRIME: "Day-1 prime",
  OUTSTANDING: "Outstanding",
  VERY_GOOD: "Very good",
  BORDERLINE: "Borderline",
  HIGH_RISK: "High risk",
};

/** Semantic colour is reserved for status; these are the only mappings that use it. */
export const BAND_TOKEN: Record<VerdictBand, string> = {
  PRIME: "var(--colour-strong)",
  OUTSTANDING: "var(--colour-strong)",
  VERY_GOOD: "var(--colour-indigo)",
  BORDERLINE: "var(--colour-caution)",
  HIGH_RISK: "var(--colour-critical)",
};

export function severityToken(severity: Severity, soft = false): string {
  const key = severity.toLowerCase();
  return `var(--colour-severity-${key}${soft ? "-soft" : ""})`;
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
}


/**
 * Human wording for the engine's internal identifiers.
 *
 * Rule ids, agent versions and check names are how the backend addresses things; showing
 * them in a dashboard reads as a debug view. Each maps to what it actually means, and an
 * unmapped id falls back to sentence-cased words rather than SCREAMING_SNAKE.
 */

const RULE_LABELS: Record<string, string> = {
  WORK_EXPERIENCE_ABSENT: "No work experience listed",
  WORK_EXPERIENCE_BELOW_BAND: "Work experience below band",
  PROJECT_DEPTH_BELOW_BAND: "Project depth below band",
  SCOPE_BULLET_INCOMPLETE: "Bullet missing an outcome",
  SCOPE_BULLET_UNQUANTIFIED: "Bullet not quantified",
  WEAK_OWNERSHIP_VERB: "Weak opening verb",
  CPI_UNVERIFIED_MISSING: "CPI not stated",
  ACADEMICS_BELOW_TRACK_BAND: "Academics below band",
  POR_SUBSTANCE_THIN: "Leadership role, thinly described",
  POR_OUTSIDE_TIER_LIST: "Role outside the Gymkhana list",
  POR_ABSENT: "No position of responsibility",
  BRANCH_MATCH_CONTEXT: "Branch weighting",
  UNVERIFIED_COMPANY: "No campus recruiting record",
  LAYOUT_MARGINS_TIGHT: "Margins too tight",
  LAYOUT_FONT_SIZE_SMALL: "Body text too small",
  LAYOUT_FONT_FAMILIES: "Too many fonts",
  LAYOUT_WORD_COUNT: "Word count outside band",
  LAYOUT_NAME_RATIO: "Name header too small",
  LAYOUT_WHITESPACE: "Line spacing outside band",
  LAYOUT_PAGE_COUNT: "More than one page",
  KB_ANALYST_TUTORIAL_DATASET: "Classroom dataset",
  KB_ANALYST_ALGORITHM_LIST: "Algorithm list",
  KB_ANALYST_METRIC_WITHOUT_BASELINE: "Metric without baseline",
  KB_SDE_UI_CLONE: "Tutorial clone project",
  KB_SDE_GENERIC_CERTIFICATE: "Generic certificate",
  KB_QUANT_WEB_CRUD: "Web project on a quant resume",
  KB_QUANT_SOFT_SKILL_FLUFF: "Unprovable claim",
  KB_CONSULT_RAW_TOOL_JARGON: "Tooling without outcome",
  AGENT_DERIVED: "Reviewer note",
};

const CHECK_LABELS: Record<string, string> = {
  UNGROUNDED_EXTRACTION: "Claim not found in the PDF",
  UNGROUNDED_REASONING: "Justification not supported",
  GROUNDING_UNAVAILABLE: "Grounding audit unavailable",
  GROUNDING_NO_SOURCE: "No source text to check against",
  ROLE_WEIGHTS_SUM: "Weighting error",
  PILLAR_BOUNDS: "Score out of range",
  SCORE_BOUNDS: "Score out of range",
  CPI_FAIL_CLOSED: "CPI policy not applied",
  CPI_UNVERIFIED: "CPI not stated",
  BRANCH_AMBIGUOUS: "Branch unclear",
  POR_OUTSIDE_TIER_LIST: "Role outside the Gymkhana list",
  POR_GENUINELY_ABSENT: "No position of responsibility",
  UNVERIFIED_COMPANY: "No campus recruiting record",
  SCORER_DIVERGENCE: "Scorers disagree",
  SEMANTIC_SANITISER_DEFAULTS: "Evaluator returned defaults",
  CHECK_CRASHED: "A check could not run",
  SPO_NO_MOBILE_NUMBER: "Mobile number on the resume",
  SPO_NO_JEE_GATE_RANK: "JEE or GATE rank on the resume",
  SPO_PAGE_COUNT: "Page count",
  SPO_FONT_COLOUR: "Non-black text",
  SPO_FONT_FAMILY_COUNT: "Too many fonts",
  SPO_PREFERRED_FONT: "Font outside the preferred list",
  SPO_CPI_MANDATORY: "CPI missing from the education table",
  SPO_EDUCATION_TABLE_ROWS: "Education table incomplete",
  SPO_EDUCATION_SCORES: "Education scores missing",
  SPO_EDUCATION_CHRONOLOGY: "Education table order",
  SPO_ACHIEVEMENT_YEAR: "Achievement without a year",
  SPO_SELF_PROJECT_LABEL: "Self project not labelled",
  SPO_ONGOING_LABEL: "Ongoing work not marked",
};

function sentenceCase(id: string): string {
  const words = id.replace(/^(KB|SPO)_/, "").toLowerCase().split(/[_\s]+/).filter(Boolean);
  if (words.length === 0) return id;
  return words[0]!.charAt(0).toUpperCase() + words[0]!.slice(1) + (words.length > 1 ? " " + words.slice(1).join(" ") : "");
}

export function ruleLabel(id: string): string {
  return RULE_LABELS[id] ?? sentenceCase(id);
}

export function checkLabel(id: string): string {
  return CHECK_LABELS[id] ?? sentenceCase(id);
}
