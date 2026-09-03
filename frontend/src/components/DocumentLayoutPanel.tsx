/**
 * How the structural score was arrived at.
 *
 * The structure score used to appear as a bare number with nothing behind it, so a
 * resume could give up 23 of its 30 layout points to margins and font families with no
 * way to see where they went. Each component is shown with what it measured, what the
 * SPO guideline asks for, and what the gap cost — sorted by cost, so the expensive
 * problems are the ones read first.
 *
 * The arithmetic is the backend's: `points_lost` arrives beside the formula that
 * produced it rather than being re-derived here, where it could drift out of step with
 * the score it claims to explain.
 */

import { AlertTriangle, Check, Eye } from "lucide-react";
import type { StructuralBreakdown, StructuralVisual } from "../lib/types";
import { Panel, SectionHeader, Tooltip } from "./primitives";

/** A component is a red flag when it gives up more than a third of its own points. */
const isRedFlag = (subScore: number) => subScore < 67;

function formatMetric(value: string | number | undefined): string {
  if (value === undefined || value === null) return "—";
  return typeof value === "number" ? `${Number(value.toFixed(2))}` : `${value}`;
}

export function DocumentLayoutPanel({
  breakdown,
  visual,
}: {
  breakdown: StructuralBreakdown;
  visual: StructuralVisual | null;
}) {
  const flags = breakdown.components.filter((c) => isRedFlag(c.sub_score));
  const lost = breakdown.components.reduce((sum, c) => sum + c.points_lost, 0);

  return (
    <Panel foldId="layout" className="p-5">
      <SectionHeader
        title="Document layout"
        eyebrow="What the structure score measures"
        meta={
          <Tooltip content="Each row is a component of the structure score, weighted as shown. Points lost is measured against the SPO guideline for this cycle.">
            <span
              tabIndex={0}
              className="text-[11px] font-medium tabular-nums"
              style={{ color: flags.length ? "var(--colour-caution)" : "var(--colour-strong)" }}
            >
              {breakdown.total}/100
            </span>
          </Tooltip>
        }
      />

      {flags.length > 0 && (
        <p className="mt-3 text-[12px] leading-relaxed" style={{ color: "var(--colour-ink-muted)" }}>
          {flags.length === 1 ? "One component is" : `${flags.length} components are`} well
          below guideline, together with the rest giving up{" "}
          <span className="font-medium tabular-nums" style={{ color: "var(--colour-ink)" }}>
            {Number(lost.toFixed(1))} of 100
          </span>{" "}
          layout points. Each appears in Recommendations under Document layout.
        </p>
      )}

      <ul className="mt-4 flex flex-col gap-2.5">
        {breakdown.components.map((c) => {
          const flag = isRedFlag(c.sub_score);
          const fill = Math.max(0, Math.min(100, c.sub_score));
          return (
            <li key={c.key} className="flex flex-col gap-1.5">
              <div className="flex items-baseline justify-between gap-3">
                <span className="flex items-center gap-1.5 text-[12px] font-medium">
                  {flag ? (
                    <AlertTriangle size={12} style={{ color: "var(--colour-caution)" }} aria-hidden />
                  ) : (
                    <Check size={12} style={{ color: "var(--colour-strong)" }} aria-hidden />
                  )}
                  {c.label}
                  <span
                    className="text-[10px] font-normal tabular-nums"
                    style={{ color: "var(--colour-ink-faint)" }}
                  >
                    {Math.round(c.weight * 100)}% weight
                  </span>
                </span>
                <span
                  className="shrink-0 text-[11px] tabular-nums"
                  style={{ color: flag ? "var(--colour-caution)" : "var(--colour-ink-faint)" }}
                >
                  {c.points_lost > 0 ? `−${Number(c.points_lost.toFixed(1))} pts` : "full marks"}
                </span>
              </div>

              {/* Track width is the component's weight, so the bar area reads as its
                  contribution to the score rather than just its percentage. */}
              <div
                className="h-1 overflow-hidden rounded-full"
                style={{
                  width: `${Math.max(12, c.weight * 100 * 2.2)}%`,
                  background: "rgba(23,38,74,0.09)",
                }}
              >
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${fill}%`,
                    background: flag ? "var(--colour-caution)" : "var(--colour-strong)",
                  }}
                />
              </div>

              {c.metric && (
                <p className="text-[11px] tabular-nums" style={{ color: "var(--colour-ink-muted)" }}>
                  {formatMetric(c.metric.ACTUAL_VALUE)}
                  <span style={{ color: "var(--colour-ink-faint)" }}>
                    {" "}
                    against guideline {formatMetric(c.metric.GUIDELINE_VALUE)}
                  </span>
                </p>
              )}
            </li>
          );
        })}
      </ul>

      {visual && (
        <div
          className="mt-4 flex items-start gap-2 rounded-lg p-3"
          style={{ background: "rgba(23,38,74,0.045)" }}
        >
          <Eye size={13} className="mt-0.5 shrink-0" style={{ color: "var(--colour-indigo)" }} aria-hidden />
          <p className="text-[11px] leading-relaxed" style={{ color: "var(--colour-ink-muted)" }}>
            A vision model read the rendered page and scored its visual layout{" "}
            <span className="font-medium tabular-nums" style={{ color: "var(--colour-ink)" }}>
              {Math.round(visual.score)}/100
            </span>
            {visual.notes?.length ? `. ${visual.notes[0]}` : "."}
          </p>
        </div>
      )}
    </Panel>
  );
}
