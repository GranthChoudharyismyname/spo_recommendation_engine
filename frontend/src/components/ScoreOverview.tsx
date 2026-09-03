import { useEffect, useState } from "react";
import { Info } from "lucide-react";
import type { EvaluationResult } from "../lib/types";
import { ValidationBadge } from "./ValidationStatus";
import { BAND_LABEL, BAND_TOKEN } from "../lib/format";
import { Chip, Panel, Tooltip } from "./primitives";

const RING_SIZE = 132;
const RING_STROKE = 9;
const RADIUS = (RING_SIZE - RING_STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export function ScoreOverview({ result }: { result: EvaluationResult }) {
  const tone = BAND_TOKEN[result.verdict_band];
  const revealed = useCountUp(result.overall_score);

  return (
    <Panel foldId="score" className="p-5">
      <div className="flex flex-wrap items-center gap-6">
        <ScoreRing score={result.overall_score} displayed={revealed} tone={tone} />

        <div className="min-w-[15rem] flex-1">
          <div className="flex items-center justify-between gap-3">
            <p className="eyebrow">Placement verdict</p>
            {result.validation ? <ValidationBadge report={result.validation} /> : null}
          </div>
          <p className="mt-1" style={{ font: "var(--type-headline)", color: tone }}>
            {BAND_LABEL[result.verdict_band]}
          </p>
          <p
            className="mt-1"
            style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}
          >
            {result.verdict}
          </p>

          <div className="mt-4 grid grid-cols-3 gap-2">
            <MetricCard
              label="Content"
              value={result.content_score}
              suffix="/100"
              note="85% of composite"
            />
            <MetricCard
              label="Structure"
              value={result.structural_score}
              suffix="/100"
              note="15% of composite"
            />
            <MetricCard label="Role" text={result.track.short_label} />
          </div>
        </div>
      </div>
    </Panel>
  );
}

export function ScoreRing({
  score,
  displayed,
  tone,
}: {
  score: number;
  displayed: number;
  tone: string;
}) {
  const offset = CIRCUMFERENCE * (1 - Math.min(100, Math.max(0, score)) / 100);
  return (
    <div className="relative shrink-0" style={{ width: RING_SIZE, height: RING_SIZE }}>
      <svg
        width={RING_SIZE}
        height={RING_SIZE}
        role="img"
        aria-label={`Score ${score} out of 100`}
      >
        <defs>
          <linearGradient id="score-arc" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={tone} />
            <stop offset="100%" stopColor="var(--colour-violet)" />
          </linearGradient>
        </defs>
        <circle
          cx={RING_SIZE / 2}
          cy={RING_SIZE / 2}
          r={RADIUS}
          fill="none"
          stroke="rgba(23,38,74,0.09)"
          strokeWidth={RING_STROKE}
        />
        <circle
          cx={RING_SIZE / 2}
          cy={RING_SIZE / 2}
          r={RADIUS}
          fill="none"
          stroke="url(#score-arc)"
          strokeWidth={RING_STROKE}
          strokeLinecap="round"
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={offset}
          transform={`rotate(-90 ${RING_SIZE / 2} ${RING_SIZE / 2})`}
          style={{ transition: "stroke-dashoffset var(--motion-slow) var(--ease-out)" }}
        />
      </svg>
      <div className="absolute inset-0 grid place-content-center text-center">
        <span
          className="data block"
          style={{ font: "var(--type-display)", color: "var(--colour-ink)" }}
        >
          {displayed}
        </span>
        <span className="data block" style={{ fontSize: 10.5, color: "var(--colour-ink-muted)" }}>
          / 100
        </span>
      </div>
    </div>
  );
}

export function MetricCard({
  label,
  value,
  text,
  suffix,
  note,
}: {
  label: string;
  value?: number;
  text?: string;
  suffix?: string;
  note?: string;
}) {
  return (
    <div className="card px-3 py-2.5">
      <p className="eyebrow">{label}</p>
      <p className="mt-1 truncate" style={{ font: "var(--type-title)" }} title={text}>
        {value !== undefined ? (
          <span className="data">
            {value}
            <span style={{ fontSize: 11, color: "var(--colour-ink-muted)" }}>{suffix}</span>
          </span>
        ) : (
          text
        )}
      </p>
      {note ? (
        <p className="data mt-0.5 truncate" style={{ fontSize: 10, color: "var(--colour-ink-faint)" }}>
          {note}
        </p>
      ) : null}
    </div>
  );
}

export function DerivedBadge({ ruleset, what }: { ruleset: string | null; what: string }) {
  if (!ruleset) return null;
  return (
    // The version string identifies the ruleset for support, but it belongs in a
    // tooltip, not on the face of the panel.
    <Tooltip content={`${what} come from fixed checks, not from the scoring model (${ruleset}).`}>
      <span tabIndex={0}>
        <Chip icon={<Info size={11} />}>Rule-based</Chip>
      </span>
    </Tooltip>
  );
}

/** Counts the headline score up once on reveal, and not at all under reduced motion. */
function useCountUp(target: number): number {
  const [value, setValue] = useState(target);
  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setValue(target);
      return;
    }
    let frame = 0;
    const start = performance.now();
    const duration = 620;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(Math.round(target * eased));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target]);
  return value;
}
