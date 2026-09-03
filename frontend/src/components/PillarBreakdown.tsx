import { ArrowUp } from "lucide-react";
import type { EvaluationResult, EvidenceAdjustment, Pillar } from "../lib/types";
import { LeverageBar } from "./LeverageBar";
import { Chip, Panel, SectionHeader, Tooltip } from "./primitives";

export function PillarBreakdown({ result }: { result: EvaluationResult }) {
  const maxWeight = Math.max(...result.pillars.map((p) => p.weight), 0.05);
  const totalHeadroom = result.pillars.reduce((sum, p) => sum + p.headroom_points, 0);

  return (
    <Panel foldId="pillars" className="p-5">
      <SectionHeader
        title="Pillar breakdown"
        eyebrow={`Weighted for ${result.track.short_label}`}
        meta={
          <Tooltip content="Bar width is the pillar's weight on this track; the fill is its score. The unfilled remainder is the headroom still available on the overall score.">
            <span tabIndex={0}>
              <Chip tone="indigo">{totalHeadroom.toFixed(1)} pts of headroom</Chip>
            </span>
          </Tooltip>
        }
      />

      <ul className="mt-4 grid gap-3.5">
        {result.pillars.map((pillar) => (
          <li key={pillar.key}>
            <PillarRow
              pillar={pillar}
              maxWeight={maxWeight}
              adjustment={result.evidence_adjustments.find((a) => a.pillar === pillar.key)}
            />
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function PillarRow({
  pillar,
  maxWeight,
  adjustment,
}: {
  pillar: Pillar;
  maxWeight: number;
  /** Set when hard evidence raised this pillar above the model's own score. */
  adjustment?: EvidenceAdjustment;
}) {
  const exhausted = pillar.headroom_points < 0.05;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <p className="truncate" style={{ font: "var(--type-title-sm)" }}>
          {pillar.label}
        </p>
        <span className="flex shrink-0 items-baseline gap-2">
          <span className="data" style={{ fontSize: 12.5, color: "var(--colour-ink)" }}>
            {pillar.score}
            <span style={{ color: "var(--colour-ink-faint)" }}>/{pillar.max_score}</span>
          </span>
          <span className="data" style={{ fontSize: 10.5, color: "var(--colour-ink-muted)" }}>
            {Math.round(pillar.weight * 100)}%
          </span>
        </span>
      </div>

      <div className="mt-1.5">
        <LeverageBar
          score={pillar.score}
          maxScore={pillar.max_score}
          weight={pillar.weight}
          maxWeight={maxWeight}
          headroom={pillar.headroom_points}
          label={pillar.label}
          tone={exhausted ? "var(--colour-strong)" : "var(--colour-indigo)"}
        />
      </div>

      {adjustment ? (
        <div
          className="mt-1.5 flex items-start gap-1.5 rounded-[var(--radius-sm)] px-2 py-1.5"
          style={{ background: "var(--colour-strong-soft)" }}
        >
          <ArrowUp size={12} className="mt-0.5 shrink-0" style={{ color: "var(--colour-strong)" }} />
          <p style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-soft)" }}>
            <span className="data" style={{ color: "var(--colour-strong)" }}>
              {adjustment.from} → {adjustment.to}
            </span>{" "}
            from hard evidence. {adjustment.reason}
          </p>
        </div>
      ) : null}

      <div className="mt-1.5">
        {pillar.tier ? (
          <p style={{ font: "var(--type-label)", color: "var(--colour-ink-muted)" }}>
            {pillar.tier}
          </p>
        ) : null}
        {pillar.reasoning ? (
          <p
            className="mt-0.5"
            style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}
          >
            {pillar.reasoning}
          </p>
        ) : null}
      </div>
    </div>
  );
}
