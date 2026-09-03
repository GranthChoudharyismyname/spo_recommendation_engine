import { useState } from "react";
import { Building2, ChevronDown, Info, ShieldQuestion } from "lucide-react";
import type { CompanyFit, CompanyFitEntry } from "../lib/types";
import { Chip, Panel, SectionHeader, Tooltip } from "./primitives";

const BAND_TONE: Record<CompanyFitEntry["fit_band"], string> = {
  Strong: "var(--colour-strong)",
  Competitive: "var(--colour-indigo)",
  Stretch: "var(--colour-caution)",
};

const INITIAL_ROWS = 6;

export function CompanyFitPanel({ fit }: { fit: CompanyFit }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? fit.entries : fit.entries.slice(0, INITIAL_ROWS);
  return (
    <Panel foldId="company-fit" className="p-5">
      <SectionHeader
        title="Estimated shortlist fit"
        eyebrow="Curated recruiter graph"
        meta={
          fit.model_version ? (
            <Tooltip content={`${fit.disclosure} (${fit.model_version})`}>
              <span tabIndex={0}>
                <Chip icon={<Info size={11} />}>Directional estimate</Chip>
              </span>
            </Tooltip>
          ) : null
        }
      />

      {!fit.available ? (
        <div className="sunken mt-4 px-4 py-6 text-center">
          <ShieldQuestion
            size={18}
            className="mx-auto mb-2"
            style={{ color: "var(--colour-ink-faint)" }}
          />
          <p style={{ font: "var(--type-title-sm)" }}>Shortlist fit unavailable</p>
          <p
            className="mx-auto mt-1 max-w-sm"
            style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}
          >
            {fit.reason ?? "The recruiter knowledge graph did not return a usable panel."}
          </p>
        </div>
      ) : (
        <>
          {fit.driving_pillar ? (
            <p
              className="mt-3"
              style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-soft)" }}
            >
              Across every row below, the pillar moving your position most is{" "}
              {fit.driving_pillar}
            </p>
          ) : null}
          <ul className="mt-4 grid gap-2">
            {visible.map((entry) => (
              <li key={entry.company_id}>
                <FitRow entry={entry} branch={fit.branch_used ?? null} />
              </li>
            ))}
          </ul>

          {fit.entries.length > INITIAL_ROWS ? (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              aria-expanded={expanded}
              className="mt-3 flex w-full items-center justify-between rounded-[var(--radius-sm)] py-1"
              style={{ font: "var(--type-title-sm)", color: "var(--colour-ink-soft)" }}
            >
              <span>
                {expanded
                  ? "Show fewer"
                  : `Show ${fit.entries.length - INITIAL_ROWS} more`}
              </span>
              <ChevronDown
                size={15}
                style={{
                  transform: expanded ? "rotate(180deg)" : "none",
                  transition: "transform var(--motion-fast) var(--ease-out)",
                }}
              />
            </button>
          ) : null}

          <p
            className="mt-4 border-t pt-3"
            style={{
              font: "var(--type-body-sm)",
              color: "var(--colour-ink-muted)",
              borderColor: "var(--colour-hairline)",
            }}
          >
            {fit.disclosure}
            {fit.campus_recruiter_pool && fit.shown ? (
              <> Ranked from {fit.campus_recruiter_pool} recruiters hiring for this role at
              IIT Kanpur.</>
            ) : null}
            {typeof fit.ppo_dominant_excluded === "number" && fit.ppo_dominant_excluded > 0 ? (
              <>
                {" "}
                {fit.ppo_dominant_excluded} firm
                {fit.ppo_dominant_excluded === 1 ? " is" : "s are"} excluded from this panel
                because they hire almost entirely through intern-to-PPO rather than the campus
                cycle.
              </>
            ) : null}
          </p>
        </>
      )}
    </Panel>
  );
}

function FitRow({ entry, branch }: { entry: CompanyFitEntry; branch: string | null }) {
  const tone = BAND_TONE[entry.fit_band];
  const recruited = (entry.presence_strength ?? 0) > 0;
  const affinity = entry.branch_affinity;
  return (
    <div className="card px-3 py-2.5">
      <div className="flex items-baseline justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate" style={{ font: "var(--type-title-sm)" }}>
            {entry.company}
          </p>
          <p
            className="truncate"
            style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-faint)" }}
          >
            {entry.category} · {entry.tier_label}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {recruited ? (
              <span
                className="inline-flex items-center gap-1 rounded-full px-2 py-0.5"
                style={{
                  font: "var(--type-label)",
                  color: "var(--colour-strong)",
                  background: "var(--colour-strong-soft)",
                }}
              >
                <Building2 size={10} /> Recruited at IITK
              </span>
            ) : null}
            {typeof affinity === "number" && affinity >= 0.1 && branch ? (
              <Tooltip content={`Share of this firm's IIT Kanpur hiring last cycle that came from ${branch}. This is the firm's history, not an eligibility criterion.`}>
                <span
                  tabIndex={0}
                  className="rounded-full px-2 py-0.5"
                  style={{
                    font: "var(--type-label)",
                    color: "var(--colour-ink-muted)",
                    background: "rgba(23,38,74,0.06)",
                  }}
                >
                  {Math.round(affinity * 100)}% from {branch}
                </span>
              </Tooltip>
            ) : null}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <span className="data" style={{ font: "var(--type-title)", color: tone }}>
            {entry.fit_score}%
          </span>
          <span className="block" style={{ font: "var(--type-label)", color: tone }}>
            {entry.fit_band}
          </span>
        </div>
      </div>

      <div
        className="mt-2 h-1.5 overflow-hidden rounded-[var(--radius-pill)]"
        style={{ background: "rgba(23,38,74,0.08)" }}
        role="img"
        aria-label={`${entry.fit_score} percent estimated fit`}
      >
        <div
          className="h-full rounded-[var(--radius-pill)]"
          style={{
            width: `${entry.fit_score}%`,
            background: tone,
            transition: "width var(--motion-slow) var(--ease-out)",
          }}
        />
      </div>

      <p className="mt-1.5" style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}>
        {entry.rationale}
      </p>
    </div>
  );
}
