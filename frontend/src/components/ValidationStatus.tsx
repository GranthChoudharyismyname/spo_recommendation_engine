/**
 * Phase 2 output — the validation report, reported at two volumes.
 *
 * `ValidationBadge` sits beside the score as a single word, because on a clean run the
 * only thing worth saying is that the score can be trusted. `ReviewNotice` appears above
 * the score when a check actually raised something, and lists it. Neither ever withholds
 * the result: validation qualifies the number, it does not replace it.
 */

import { AlertTriangle, ShieldAlert, ShieldCheck } from "lucide-react";
import type { ValidationReport, ValidationStatus } from "../lib/types";
import { Tooltip } from "./primitives";

const STATUS: Record<
  ValidationStatus,
  { label: string; tone: string; soft: string; icon: typeof ShieldCheck }
> = {
  PASS: {
    label: "Validated",
    tone: "var(--colour-strong)",
    soft: "var(--colour-strong-soft)",
    icon: ShieldCheck,
  },
  PASS_WITH_WARNINGS: {
    label: "Validated with warnings",
    tone: "var(--colour-caution)",
    soft: "var(--colour-caution-soft)",
    icon: ShieldAlert,
  },
  NEEDS_REVIEW: {
    label: "Needs review",
    tone: "var(--colour-critical)",
    soft: "var(--colour-critical-soft)",
    icon: AlertTriangle,
  },
};

/**
 * Validation, as one word rather than a panel.
 *
 * It used to occupy a full section reporting grounding coverage, finding counts and
 * checks run. On a clean evaluation — which is most of them — that is three statistics
 * all saying "nothing is wrong", which reads like instrumentation rather than an
 * answer. The status is what the reader needs; the numbers behind it belong in the
 * tooltip, and anything actually worth acting on is raised by `ReviewNotice` instead.
 */
export function ValidationBadge({ report }: { report: ValidationReport }) {
  const status = STATUS[report.status];
  const Icon = status.icon;
  const coverage = report.grounding_coverage;
  const actionable = report.counts.blocking + report.counts.warning;

  const detail = [
    coverage === null
      ? "Grounding was not audited."
      : `${Math.round(coverage * 100)}% of ${report.claims_audited} extracted claims were traced back to your PDF.`,
    actionable === 0
      ? `All ${report.checks_run.length} checks passed.`
      : `${actionable} of ${report.checks_run.length} checks raised something.`,
  ].join(" ");

  return (
    <Tooltip content={detail}>
      <span
        tabIndex={0}
        className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1"
        style={{ font: "var(--type-label)", color: status.tone, background: status.soft }}
      >
        <Icon size={13} aria-hidden />
        {status.label}
      </span>
    </Tooltip>
  );
}


export function ReviewNotice({ report }: { report: ValidationReport }) {
  // Warnings used to live in the panel's finding list. With the panel gone they surface
  // here, so removing the instrumentation never removes something worth acting on.
  const raised = report.findings.filter(
    (f) => f.severity === "CRITICAL" || f.severity === "WARNING",
  );
  if (raised.length === 0) return null;
  const critical = raised.filter((f) => f.severity === "CRITICAL");
  const tone = critical.length ? "var(--colour-critical)" : "var(--colour-caution)";

  return (
    <div
      role="status"
      className="rounded-[var(--radius-md)] border px-4 py-3"
      style={{
        borderColor: `color-mix(in srgb, ${tone} 32%, transparent)`,
        background: critical.length
          ? "var(--colour-critical-soft)"
          : "var(--colour-caution-soft)",
      }}
    >
      <p
        className="flex items-center gap-2"
        style={{ font: "var(--type-title-sm)", color: tone }}
      >
        <AlertTriangle size={14} />
        {raised.length === 1
          ? "One finding to check against your PDF"
          : `${raised.length} findings to check against your PDF`}
      </p>
      <ul className="mt-1.5 grid gap-1">
        {raised.map((finding, index) => (
          <li
            key={`${finding.check}-${index}`}
            style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-soft)" }}
          >
            {finding.message}
          </li>
        ))}
      </ul>
      <p
        className="mt-2"
        style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}
      >
        The score and recommendations below are still shown — read them with this in mind.
      </p>
    </div>
  );
}
