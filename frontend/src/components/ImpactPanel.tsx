/**
 * Quantified results.
 *
 * The numbers a candidate reports are what turn "described the work" into "showed what
 * it achieved", so they get their own panel rather than being buried in the raw signals.
 * Extracted deterministically in the same {metric, direction, value, unit} shape the
 * signal corpora use, and every figure carries the bullet it came from.
 *
 * The headline is the ratio, not the count: twelve metrics spread over four bullets is a
 * different resume from twelve spread over twelve.
 */

import { ArrowDownRight, ArrowUpRight, Minus, Trophy } from "lucide-react";
import type { QuantifiedResult, QuantifiedResultsSummary } from "../lib/types";
import { Chip, Panel, SectionHeader, Tooltip } from "./primitives";

const DIRECTION_ICON = {
  decrease: ArrowDownRight,
  increase: ArrowUpRight,
  top: Trophy,
  achieved: Minus,
} as const;

function formatValue(r: QuantifiedResult): string {
  const v = r.value;
  const n =
    v >= 1_000_000 ? `${(v / 1_000_000).toFixed(v % 1_000_000 ? 1 : 0)}M`
    : v >= 1_000 ? `${(v / 1_000).toFixed(v % 1_000 ? 1 : 0)}K`
    : `${Number.isInteger(v) ? v : v.toFixed(2).replace(/\.?0+$/, "")}`;
  const unit =
    r.unit === "percent" ? "%"
    : r.unit === "x" ? "×"
    : r.unit === "milliseconds" ? " ms"
    : r.unit === "seconds" ? " s"
    : r.unit === "bytes" ? " KB"
    : r.unit ? ` ${r.unit}` : "";
  return `${n}${unit}`;
}

export function ImpactPanel({
  results,
  summary,
}: {
  results: QuantifiedResult[];
  summary: QuantifiedResultsSummary;
}) {
  const ratio = summary.quantified_bullet_ratio;
  const tone =
    ratio >= 0.5 ? "var(--colour-strong)"
    : ratio >= 0.3 ? "var(--colour-indigo)"
    : "var(--colour-caution)";

  return (
    <Panel foldId="impact" className="p-5">
      <SectionHeader
        title="Quantified impact"
        eyebrow="Extracted from your bullets"
        meta={
          <Tooltip content="Bullets that state a measured result, out of all bullets in Work Experience, Projects, Competitions and PoR. This ratio is what the SCOPE pillar is really measuring.">
            <span tabIndex={0}>
              <Chip>
                {summary.quantified_bullets}/{summary.total_bullets} bullets
              </Chip>
            </span>
          </Tooltip>
        }
      />

      <div className="mt-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="data" style={{ font: "var(--type-headline)", color: tone }}>
          {Math.round(ratio * 100)}%
        </span>
        <span style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}>
          of your bullets state a measured result — {summary.total} figures in total
        </span>
      </div>

      {results.length === 0 ? (
        <p
          className="mt-3"
          style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}
        >
          No quantified results were found. Bullets that describe the method without the
          outcome cannot be sized by a reviewer.
        </p>
      ) : (
        <ul className="mt-4 grid gap-1.5">
          {results.map((r, i) => {
            const Icon = r.direction ? DIRECTION_ICON[r.direction] : Minus;
            const dirTone =
              r.direction === "decrease" || r.direction === "increase" || r.direction === "top"
                ? "var(--colour-strong)"
                : "var(--colour-ink-faint)";
            return (
              <li key={`${r.value}-${r.metric}-${i}`}>
                <Tooltip content={r.evidence} side="top">
                  <div
                    tabIndex={0}
                    className="sunken flex flex-wrap items-baseline gap-x-2.5 gap-y-1 px-3 py-2"
                  >
                    <Icon size={12} className="shrink-0" style={{ color: dirTone }} />
                    <span
                      className="data"
                      style={{ fontSize: 13, color: "var(--colour-ink)", minWidth: "5rem" }}
                    >
                      {formatValue(r)}
                    </span>
                    <span
                      style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-soft)" }}
                    >
                      {r.metric ?? <em style={{ color: "var(--colour-ink-faint)" }}>unnamed</em>}
                    </span>
                    <span
                      className="data ml-auto truncate"
                      style={{ fontSize: 10, color: "var(--colour-ink-faint)", maxWidth: "14rem" }}
                    >
                      {r.entry || r.section}
                    </span>
                  </div>
                </Tooltip>
              </li>
            );
          })}
        </ul>
      )}

      {summary.named_metrics.length > 0 ? (
        <p
          className="mt-3 border-t pt-3"
          style={{
            font: "var(--type-body-sm)",
            color: "var(--colour-ink-muted)",
            borderColor: "var(--colour-hairline)",
          }}
        >
          Metrics named: {summary.named_metrics.join(" · ")}
        </p>
      ) : null}
    </Panel>
  );
}
