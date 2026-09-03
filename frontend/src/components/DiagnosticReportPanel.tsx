/**
 * The three named report sections: strengths, critical gaps, formatting fixes.
 *
 * Strengths lead deliberately. Every other panel in this dashboard names a problem, and
 * a report that only lists faults reads as a verdict on the candidate rather than advice
 * for them — which is the opposite of what a diagnostic is for. Each strength carries
 * the evidence it rests on, so it reads as an observation rather than encouragement.
 */

import { AlertTriangle, CheckCircle2, Ruler } from "lucide-react";
import type { DiagnosticReport } from "../lib/types";
import { Panel, SectionHeader } from "./primitives";

const TONE = {
  strength: "var(--colour-strong)",
  gap: "var(--colour-critical)",
  fix: "var(--colour-caution)",
} as const;

function Block({
  tone,
  icon,
  title,
  count,
  children,
}: {
  tone: keyof typeof TONE;
  icon: React.ReactNode;
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-5 first:mt-0">
      <h3
        className="flex items-center gap-2"
        style={{ font: "var(--type-title-sm)", color: TONE[tone] }}
      >
        {icon}
        {title}
        <span
          className="tabular-nums"
          style={{ font: "var(--type-label)", color: "var(--colour-ink-faint)" }}
        >
          {count}
        </span>
      </h3>
      <ul className="mt-2 grid gap-2">{children}</ul>
    </section>
  );
}

function Row({
  tone,
  title,
  body,
  meta,
  badge,
}: {
  tone: keyof typeof TONE;
  title: string;
  body: string;
  meta?: string;
  badge?: string;
}) {
  return (
    <li
      className="rounded-[var(--radius-md)] p-3"
      style={{
        background: "var(--colour-glass-sunken)",
        borderLeft: `3px solid ${TONE[tone]}`,
      }}
    >
      <div className="flex items-baseline justify-between gap-3">
        <p style={{ font: "var(--type-title-sm)", color: "var(--colour-ink)" }}>{title}</p>
        {badge ? (
          <span
            className="shrink-0 tabular-nums"
            style={{ font: "var(--type-label)", color: TONE[tone] }}
          >
            {badge}
          </span>
        ) : null}
      </div>
      <p
        className="mt-1"
        style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}
      >
        {body}
      </p>
      {meta ? (
        <p
          className="mt-1.5 tabular-nums"
          style={{ font: "var(--type-label)", color: "var(--colour-ink-faint)" }}
        >
          {meta}
        </p>
      ) : null}
    </li>
  );
}

export function DiagnosticReportPanel({ report }: { report: DiagnosticReport }) {
  const { top_strengths, critical_missing, formatting_fixes } = report;
  if (!top_strengths.length && !critical_missing.length && !formatting_fixes.length) return null;

  return (
    <Panel foldId="report" className="p-5">
      <SectionHeader title="Diagnostic report" eyebrow="What is working, what is not" />

      {top_strengths.length > 0 ? (
        <Block
          tone="strength"
          icon={<CheckCircle2 size={14} aria-hidden />}
          title="Top strengths"
          count={top_strengths.length}
        >
          {top_strengths.map((s) => (
            <Row key={s.title} tone="strength" title={s.title} body={s.detail} meta={s.evidence} />
          ))}
        </Block>
      ) : null}

      {critical_missing.length > 0 ? (
        <Block
          tone="gap"
          icon={<AlertTriangle size={14} aria-hidden />}
          title="Critical missing elements"
          count={critical_missing.length}
        >
          {critical_missing.map((g, i) => (
            <Row
              key={`${g.source}-${i}`}
              tone="gap"
              title={g.title}
              body={g.why}
              meta={g.section ?? undefined}
              badge={
                g.blocking
                  ? "blocks submission"
                  : g.impact_points
                    ? `up to +${g.impact_points}`
                    : undefined
              }
            />
          ))}
        </Block>
      ) : null}

      {formatting_fixes.length > 0 ? (
        <Block
          tone="fix"
          icon={<Ruler size={14} aria-hidden />}
          title="Line-by-line formatting fixes"
          count={formatting_fixes.length}
        >
          {formatting_fixes.map((f, i) => (
            <Row
              key={`${f.source}-${i}`}
              tone="fix"
              title={f.title}
              body={f.fix}
              // Layout findings carry the region they were measured from, so each fix
              // can name the place on the page it refers to.
              meta={
                f.evidence_refs[0]
                  ? `page ${f.evidence_refs[0].page} · ${f.detail}`
                  : f.detail
              }
              badge={f.impact_points ? `+${f.impact_points}` : undefined}
            />
          ))}
        </Block>
      ) : null}
    </Panel>
  );
}
