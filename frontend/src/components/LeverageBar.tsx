/**
 * Leverage bar.
 *
 * A plain progress bar per pillar would say "16 out of 20" five times over and imply
 * every pillar matters equally. They do not: the track weighting decides how much a
 * pillar can move the score at all.
 *
 * So the track width is the pillar's weight and the fill is its score. Filled area is
 * literally the pillar's contribution to the content score; the empty remainder is the
 * headroom, and it is the same number the recommendations quote as expected impact.
 * A 25%-weight pillar's bar is five times the width of a 5% one, because it is worth
 * five times as much.
 */

import { Tooltip } from "./primitives";

export function LeverageBar({
  score,
  maxScore,
  weight,
  maxWeight,
  headroom,
  label,
  tone = "var(--colour-indigo)",
}: {
  score: number;
  maxScore: number;
  weight: number;
  maxWeight: number;
  headroom: number;
  label: string;
  tone?: string;
}) {
  // Width proportional to weight, floored so the lightest pillar stays readable.
  const trackPercent = Math.max(14, (weight / Math.max(maxWeight, 0.0001)) * 100);
  const fillPercent = maxScore > 0 ? (score / maxScore) * 100 : 0;

  return (
    <Tooltip
      side="top"
      content={
        <div className="space-y-0.5">
          <p style={{ font: "var(--type-title-sm)" }}>{label}</p>
          <p>
            Scored {score} of {maxScore}, weighted {Math.round(weight * 100)}% on this track.
          </p>
          <p>
            Bar width is the weight; the unfilled part is {headroom.toFixed(1)} points of
            headroom on the overall score.
          </p>
        </div>
      }
    >
      <div className="w-full" tabIndex={0}>
        <div
          className="relative h-2.5 overflow-hidden rounded-[var(--radius-pill)]"
          style={{
            width: `${trackPercent}%`,
            background: "rgba(23,38,74,0.09)",
            border: "1px solid var(--colour-hairline)",
          }}
        >
          <div
            className="h-full rounded-[var(--radius-pill)]"
            style={{
              width: `${fillPercent}%`,
              background: `linear-gradient(90deg, ${tone}, color-mix(in oklab, ${tone} 72%, var(--colour-violet)))`,
              transition: `width var(--motion-slow) var(--ease-out)`,
            }}
          />
        </div>
      </div>
    </Tooltip>
  );
}
