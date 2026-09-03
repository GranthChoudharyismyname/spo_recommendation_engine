/**
 * SCOPE meter.
 *
 * The role knowledge bases evaluate every resume bullet against five dimensions —
 * Scale, Context, Own, Proof, Edge. The backend reports which ones a specific bullet
 * actually carries, and this renders that verdict directly: five capsules, filled for
 * the dimensions present, hollow for the ones missing.
 *
 * It is the one place a reader can see *why* a bullet scored the way it did, so it is
 * the only ornament on a recommendation card.
 */

import type { ScopeDimension } from "../lib/types";
import { Tooltip } from "./primitives";

const ORDER: ScopeDimension[] = ["SCALE", "CONTEXT", "OWN", "PROOF", "EDGE"];

const MEANING: Record<ScopeDimension, string> = {
  SCALE: "Scale — how big the stakes were",
  CONTEXT: "Context — the real data or constraint involved",
  OWN: "Own — the decision or design you made",
  PROOF: "Proof — evidence the work landed",
  EDGE: "Edge — the measured outcome",
};

export function ScopeMeter({
  present,
  compact = false,
}: {
  present: ScopeDimension[];
  compact?: boolean;
}) {
  const set = new Set(present);
  const covered = ORDER.filter((d) => set.has(d)).length;

  return (
    <Tooltip
      content={
        <div className="space-y-1">
          <p style={{ font: "var(--type-title-sm)" }}>
            SCOPE coverage {covered} of 5
          </p>
          {ORDER.map((dim) => (
            <p key={dim} style={{ opacity: set.has(dim) ? 1 : 0.55 }}>
              {set.has(dim) ? "●" : "○"} {MEANING[dim]}
            </p>
          ))}
        </div>
      }
    >
      <span
        className="inline-flex items-center gap-1.5"
        tabIndex={0}
        role="img"
        aria-label={`SCOPE coverage ${covered} of 5: ${ORDER.filter((d) => set.has(d)).join(", ") || "none"}`}
      >
        <span className="flex items-center gap-[3px]">
          {ORDER.map((dim) => {
            const on = set.has(dim);
            return (
              <span
                key={dim}
                aria-hidden
                className="grid place-items-center rounded-[3px] transition-colors"
                style={{
                  width: compact ? 13 : 15,
                  height: compact ? 13 : 15,
                  font: "600 8.5px/1 var(--font-data)",
                  color: on ? "#fff" : "var(--colour-ink-faint)",
                  background: on ? "var(--colour-indigo)" : "transparent",
                  border: on ? "none" : "1px solid var(--colour-hairline-strong)",
                  transitionDuration: "var(--motion-fast)",
                }}
              >
                {dim.charAt(0)}
              </span>
            );
          })}
        </span>
        {!compact && (
          <span className="data" style={{ fontSize: 10.5, color: "var(--colour-ink-muted)" }}>
            {covered}/5
          </span>
        )}
      </span>
    </Tooltip>
  );
}
