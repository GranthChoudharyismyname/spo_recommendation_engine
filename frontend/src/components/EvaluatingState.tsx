/**
 * The centre column while an evaluation is in flight.
 *
 * A skeleton implies content is about to snap in; a run here takes 60-120 seconds
 * because it makes six model calls, so the panel has to say what it is doing rather
 * than sit blank. The mark draws itself: the gauge sweep advances with the stage, the
 * resume lines fill in one at a time, and the reading tick appears at the end.
 *
 * Stage labels are the honest ones — the API answers once, so these describe the
 * pipeline's stages rather than claiming server-reported progress.
 */

import { useEffect, useState } from "react";
import { Check, Loader2 } from "lucide-react";
import { PROGRESS_STEPS } from "../lib/evaluationState";
import { Panel } from "./primitives";

const STAGE_NOTE: Record<number, string> = {
  0: "Sending the PDF to the scoring service.",
  1: "Measuring margins, fonts and word count against the SPO guidelines.",
  2: "Reading the document into the 14-section schema.",
  3: "Scoring the six pillars against the role framework.",
  4: "Checking the result for grounding, then writing recommendations.",
};

const RING_CIRCUMFERENCE = 2 * Math.PI * 23;

export function EvaluatingState({ stepIndex }: { stepIndex: number }) {
  const [elapsed, setElapsed] = useState(0);
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    setReduced(window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    const id = window.setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => window.clearInterval(id);
  }, []);

  const total = PROGRESS_STEPS.length;
  const stage = Math.min(stepIndex, total - 1);
  const progress = Math.min(1, (stage + 0.5) / total);
  // The mark's arc is a 260-degree sweep, so the reading fills that span.
  const offset = RING_CIRCUMFERENCE * (1 - progress * (260 / 360));

  return (
    <Panel className="grid place-items-center px-6 py-16">
      <div className="flex flex-col items-center text-center">
        <svg width={112} height={112} viewBox="0 0 64 64" fill="none" role="img" aria-label="Evaluating">
          <defs>
            <linearGradient id="ev-sweep" x1="10" y1="54" x2="54" y2="12" gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor="var(--colour-indigo)" />
              <stop offset="1" stopColor="var(--colour-violet)" />
            </linearGradient>
          </defs>

          <path
            d="M 15.6 50.9 A 23 23 0 1 1 48.4 50.9"
            stroke="var(--colour-hairline-strong)"
            strokeWidth={6}
            strokeLinecap="round"
          />
          <path
            d="M 15.6 50.9 A 23 23 0 1 1 48.4 50.9"
            stroke="url(#ev-sweep)"
            strokeWidth={6}
            strokeLinecap="round"
            strokeDasharray={RING_CIRCUMFERENCE}
            strokeDashoffset={offset}
            style={{ transition: "stroke-dashoffset 900ms var(--ease-out)" }}
          />

          <g strokeWidth={4} strokeLinecap="round">
            {[
              { y: 26, x2: 42, at: 1 },
              { y: 36, x2: 37, at: 2 },
              { y: 46, x2: 31, at: 3 },
            ].map((line) => (
              <line
                key={line.y}
                x1={24}
                y1={line.y}
                x2={line.x2}
                y2={line.y}
                stroke={stage >= line.at ? "var(--colour-ink)" : "var(--colour-hairline-strong)"}
                style={{ transition: "stroke 500ms var(--ease-out)" }}
              />
            ))}
          </g>

          <circle
            cx="48.4"
            cy="50.9"
            r="4.8"
            fill="var(--colour-violet)"
            style={{
              opacity: stage >= total - 1 ? 1 : 0,
              transition: "opacity 500ms var(--ease-out)",
            }}
          />
        </svg>

        <p className="mt-5" style={{ font: "var(--type-headline)", color: "var(--colour-ink)" }}>
          {PROGRESS_STEPS[stage]?.label ?? "Evaluating"}
        </p>
        <p
          className="mt-1.5 max-w-sm"
          style={{ font: "var(--type-body)", color: "var(--colour-ink-muted)" }}
        >
          {STAGE_NOTE[stage]}
        </p>

        <div className="mt-5 flex items-center gap-2">
          {PROGRESS_STEPS.map((step, index) => (
            <span
              key={step.label}
              aria-hidden
              className="h-1.5 rounded-full"
              style={{
                width: index === stage ? 28 : 14,
                background:
                  index < stage
                    ? "var(--colour-strong)"
                    : index === stage
                      ? "var(--colour-indigo)"
                      : "var(--colour-hairline-strong)",
                transition: "width 400ms var(--ease-out), background 400ms var(--ease-out)",
              }}
            />
          ))}
        </div>

        <p
          className="data mt-4"
          style={{ fontSize: 11, color: "var(--colour-ink-faint)" }}
          aria-live="polite"
        >
          {reduced ? (
            <Check size={11} className="mr-1 inline" />
          ) : (
            <Loader2 size={11} className="mr-1 inline animate-spin" />
          )}
          {elapsed}s · a full run makes six model calls, usually 60–120s
        </p>
      </div>
    </Panel>
  );
}
