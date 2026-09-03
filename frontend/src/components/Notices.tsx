import { AlertTriangle, FlaskConical, RotateCcw, ShieldAlert, WifiOff } from "lucide-react";
import type { Compliance, EvaluationWarning } from "../lib/types";
import type { FailureState } from "../lib/evaluationState";
import { checkLabel } from "../lib/format";
import { Button, Chip, Panel, SectionHeader } from "./primitives";

export function DegradedBanner({
  warnings,
  title,
}: {
  warnings: EvaluationWarning[];
  /** Overrides the default headline, which assumes a result exists to be partial. */
  title?: string;
}) {
  if (warnings.length === 0) return null;
  return (
    <div
      role="status"
      className="rounded-[var(--radius-md)] border px-4 py-3"
      style={{
        borderColor: "color-mix(in srgb, var(--colour-caution) 34%, transparent)",
        background: "var(--colour-caution-soft)",
      }}
    >
      <p
        className="flex items-center gap-2"
        style={{ font: "var(--type-title-sm)", color: "var(--colour-caution)" }}
      >
        <AlertTriangle size={14} />
        {title ??
          (warnings.length === 1
            ? "Partial result — one part of this evaluation is incomplete"
            : `Partial result — ${warnings.length} parts of this evaluation are incomplete`)}
      </p>
      <ul className="mt-2 grid gap-1.5">
        {warnings.map((warning, index) => (
          <li
            key={`${warning.code}-${index}`}
            className="flex flex-wrap items-baseline gap-x-2"
            style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-soft)" }}
          >
            <span className="min-w-0 flex-1">{warning.message}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Fixture sessions get their own notice.
 *
 * Reusing the degraded-result banner said "Partial result — incomplete", which reads as
 * a broken evaluation. A demo session is neither partial nor broken: it is complete data
 * about a different document, and the distinction matters because the whole point of the
 * degraded banner is that it should be alarming.
 */
export function FixtureNotice({ notes }: { notes: string[] }) {
  if (notes.length === 0) return null;
  return (
    <div
      className="rounded-[var(--radius-md)] border px-4 py-3"
      style={{
        borderColor: "color-mix(in srgb, var(--colour-indigo) 26%, transparent)",
        background: "var(--colour-indigo-soft)",
      }}
    >
      <p
        className="flex items-center gap-2"
        style={{ font: "var(--type-title-sm)", color: "var(--colour-indigo-deep)" }}
      >
        <FlaskConical size={14} />
        Fixture session — this is sample data, not your resume
      </p>
      <ul className="mt-1.5 grid gap-1">
        {notes.map((note) => (
          <li key={note} style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-soft)" }}>
            {note}
          </li>
        ))}
      </ul>

    </div>
  );
}

export function CompliancePanel({ compliance }: { compliance: Compliance }) {
  if (compliance.status === "UNAVAILABLE") return null;

  const tone =
    compliance.status === "NON_COMPLIANT"
      ? "critical"
      : compliance.status === "REVIEW_REQUIRED"
        ? "caution"
        : "strong";
  const label =
    compliance.status === "NON_COMPLIANT"
      ? "Blocked for submission"
      : compliance.status === "REVIEW_REQUIRED"
        ? "Review before submitting"
        : "Meets SPO submission rules";

  return (
    <Panel className="p-5" foldId="compliance">
      <SectionHeader
        title="SPO submission compliance"
        eyebrow="Checked separately from the score"
        meta={<Chip tone={tone}>{label}</Chip>}
      />

      {compliance.findings.length === 0 ? (
        <p
          className="mt-3"
          style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}
        >
          No submission-rule violations were found. These checks are pass/fail policy and
          do not affect the composite score.
        </p>
      ) : (
        <ul className="mt-4 grid gap-2">
          {compliance.findings.map((finding) => {
            const colour =
              finding.severity === "BLOCKING"
                ? "var(--colour-critical)"
                : finding.severity === "WARNING"
                  ? "var(--colour-caution)"
                  : "var(--colour-ink-muted)";
            return (
              <li key={finding.check} className="card px-3 py-2.5">
                <div className="flex flex-wrap items-center gap-1.5">
                  <ShieldAlert size={13} style={{ color: colour }} />
                  <span
                    className="rounded-full px-2 py-0.5"
                    style={{
                      font: "var(--type-label)",
                      color: colour,
                      background: `color-mix(in srgb, ${colour} 12%, transparent)`,
                    }}
                  >
                    {finding.severity === "BLOCKING" ? "Blocking" : finding.severity === "WARNING" ? "Warning" : "Note"}
                  </span>
                  <span style={{ font: "var(--type-label)", color: "var(--colour-ink-faint)" }}>
                    {checkLabel(finding.check)}
                  </span>
                </div>
                <p className="mt-1.5" style={{ font: "var(--type-body-sm)", color: "var(--colour-ink)" }}>
                  {finding.message}
                </p>
                <p className="mt-1" style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}>
                  {finding.guideline}
                </p>
                {finding.evidence ? (
                  <p className="data mt-1" style={{ fontSize: 10.5, color: "var(--colour-ink-faint)" }}>
                    Found: {finding.evidence}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

export function FailurePanel({
  failure,
  onRetry,
}: {
  failure: FailureState;
  onRetry: () => void;
}) {
  const Icon = failure.code === "NETWORK" ? WifiOff : AlertTriangle;
  return (
    <Panel className="p-6">
      <div className="flex items-start gap-3">
        <span
          className="grid h-9 w-9 shrink-0 place-items-center rounded-[var(--radius-sm)]"
          style={{ background: "var(--colour-critical-soft)", color: "var(--colour-critical)" }}
        >
          <Icon size={17} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 style={{ font: "var(--type-title)" }}>{failure.title}</h2>
          <p
            className="mt-1"
            style={{ font: "var(--type-body)", color: "var(--colour-ink-soft)" }}
          >
            {failure.message}
          </p>
          {failure.problems?.length ? (
            <ul className="mt-3 grid gap-1">
              {failure.problems.map((problem) => (
                <li
                  key={problem}
                  style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}
                >
                  · {problem}
                </li>
              ))}
            </ul>
          ) : null}
          <p
            className="mt-3"
            style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}
          >
            No score is shown for a failed run. A partial or fabricated result would be
            worse than none.
          </p>
          {failure.retryable ? (
            <div className="mt-4">
              <Button onClick={onRetry} icon={<RotateCcw size={14} />}>
                Try again
              </Button>
            </div>
          ) : null}
        </div>
      </div>
    </Panel>
  );
}

export function ResultsPlaceholder() {
  return (
    <Panel className="grid place-content-center px-6 py-16 text-center">
      <p style={{ font: "var(--type-headline)" }}>Nothing evaluated yet</p>
      <p
        className="mx-auto mt-2 max-w-sm"
        style={{ font: "var(--type-body)", color: "var(--colour-ink-muted)" }}
      >
        Add a PDF resume, choose the role you are targeting, and run the evaluation. The
        score, its breakdown and the evidence behind each recommendation appear here.
      </p>
    </Panel>
  );
}

export function ResultsSkeleton() {
  return (
    <div className="grid gap-4">
      <Panel className="p-5">
        <div className="flex gap-6">
          <div className="skeleton h-[132px] w-[132px] rounded-full" />
          <div className="flex-1 space-y-3 pt-3">
            <div className="skeleton h-3 w-24" />
            <div className="skeleton h-6 w-48" />
            <div className="grid grid-cols-3 gap-2 pt-2">
              <div className="skeleton h-16" />
              <div className="skeleton h-16" />
              <div className="skeleton h-16" />
            </div>
          </div>
        </div>
      </Panel>
      <Panel className="space-y-3 p-5">
        <div className="skeleton h-4 w-40" />
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="skeleton h-24" />
        ))}
      </Panel>
    </div>
  );
}
