import { useEffect, useMemo, useRef, useState } from "react";
import { CircleSlash, MapPin, Pin, Quote, Target } from "lucide-react";
import type { Recommendation, ScopeDimension, Severity } from "../lib/types";
import { SEVERITY_LABEL, SEVERITY_ORDER, ruleLabel, severityToken, truncate } from "../lib/format";
import { ScopeMeter } from "./ScopeMeter";
import { Chip, Panel, SectionHeader, Tooltip } from "./primitives";
import { DerivedBadge } from "./ScoreOverview";

export function RecommendationSummary({
  counts,
  active,
  onFilter,
}: {
  counts: { high: number; important: number; polish: number };
  active: Severity | null;
  onFilter: (severity: Severity | null) => void;
}) {
  const values: Record<Severity, number> = {
    HIGH: counts.high,
    IMPORTANT: counts.important,
    POLISH: counts.polish,
  };
  return (
    <div className="grid grid-cols-3 gap-2">
      {SEVERITY_ORDER.map((severity) => {
        const selected = active === severity;
        return (
          <button
            key={severity}
            type="button"
            aria-pressed={selected}
            onClick={() => onFilter(selected ? null : severity)}
            className="card px-3 py-2.5 text-left transition-[background,border-color]"
            style={{
              borderColor: selected ? severityToken(severity) : "var(--colour-hairline)",
              background: selected ? severityToken(severity, true) : "var(--colour-glass-raised)",
              transitionDuration: "var(--motion-fast)",
            }}
          >
            <span className="flex items-baseline gap-2">
              <span
                className="data"
                style={{ font: "var(--type-headline)", color: severityToken(severity) }}
              >
                {values[severity]}
              </span>
            </span>
            <span
              className="mt-0.5 block"
              style={{ font: "var(--type-label)", color: "var(--colour-ink-muted)" }}
            >
              {SEVERITY_LABEL[severity]}
            </span>
          </button>
        );
      })}
    </div>
  );
}

export function RecommendationList({
  recommendations,
  ruleset,
  activeId,
  pinnedId,
  onActivate,
  onPin,
}: {
  recommendations: Recommendation[];
  ruleset: string;
  activeId: string | null;
  pinnedId: string | null;
  onActivate: (id: string | null) => void;
  onPin: (id: string) => void;
}) {
  const [filter, setFilter] = useState<Severity | null>(null);

  const counts = useMemo(
    () => ({
      high: recommendations.filter((r) => r.severity === "HIGH").length,
      important: recommendations.filter((r) => r.severity === "IMPORTANT").length,
      polish: recommendations.filter((r) => r.severity === "POLISH").length,
    }),
    [recommendations],
  );

  const visible = filter ? recommendations.filter((r) => r.severity === filter) : recommendations;

  return (
    <Panel foldId="recommendations" className="p-5">
      <SectionHeader
        title="Checks"
        eyebrow="Prioritised by where the points are"
        meta={<DerivedBadge ruleset={ruleset} what="These checks" />}
      />

      {recommendations.length === 0 ? (
        <EmptyRecommendations />
      ) : (
        <>
          <div className="mt-4">
            <RecommendationSummary counts={counts} active={filter} onFilter={setFilter} />
          </div>
          <ul className="mt-4 grid gap-2.5">
            {visible.map((rec) => (
              <li key={rec.id}>
                <RecommendationCard
                  recommendation={rec}
                  active={activeId === rec.id}
                  pinned={pinnedId === rec.id}
                  onActivate={onActivate}
                  onPin={onPin}
                />
              </li>
            ))}
          </ul>
          {visible.length === 0 ? (
            <p
              className="mt-4"
              style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}
            >
              Nothing at this severity. Clear the filter to see the rest.
            </p>
          ) : null}
        </>
      )}
    </Panel>
  );
}

export function RecommendationCard({
  recommendation: rec,
  active,
  pinned,
  onActivate,
  onPin,
}: {
  recommendation: Recommendation;
  active: boolean;
  pinned: boolean;
  onActivate: (id: string | null) => void;
  onPin: (id: string) => void;
}) {
  const tone = severityToken(rec.severity);
  const hasEvidence = rec.evidence_refs.length > 0;
  const scopePresent = (rec.detail.scope_present ?? []) as ScopeDimension[];
  const showScope = Boolean(rec.detail.scope_total);

  /*
   * Settle briefly before claiming the highlight.
   *
   * Reading down the list drags the cursor across every card in between, and reacting to
   * each one makes the viewer flicker through evidence nobody asked to see. A short
   * pause means only a card the pointer actually rests on takes effect; leaving cancels
   * it, so a sweep costs nothing.
   */
  const hoverTimer = useRef<number | undefined>(undefined);
  const settle = (id: string | null) => {
    window.clearTimeout(hoverTimer.current);
    hoverTimer.current = window.setTimeout(() => onActivate(id), id ? 110 : 0);
  };
  useEffect(() => () => window.clearTimeout(hoverTimer.current), []);

  return (
    <article
      // Hover and keyboard focus both drive the highlight; hover alone would make the
      // evidence link unreachable without a pointer. Keyboard focus is deliberate, so it
      // applies at once where hover waits.
      onMouseEnter={() => settle(rec.id)}
      onMouseLeave={() => settle(null)}
      onFocus={() => onActivate(rec.id)}
      onBlur={() => onActivate(null)}
      onClick={() => onPin(rec.id)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onPin(rec.id);
        }
      }}
      tabIndex={0}
      role="button"
      aria-pressed={pinned}
      aria-label={`${SEVERITY_LABEL[rec.severity]}: ${rec.title}. ${
        hasEvidence ? "Press Enter to pin its evidence in the resume viewer." : "No evidence location."
      }`}
      className="card cursor-pointer p-3.5 transition-[border-color,box-shadow,transform]"
      style={{
        borderColor: pinned ? tone : active ? "var(--colour-indigo)" : "var(--colour-hairline)",
        boxShadow: active || pinned ? "var(--shadow-raised)" : "var(--shadow-flat)",
        borderLeft: `3px solid ${tone}`,
        transitionDuration: "var(--motion-fast)",
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <span
            className="rounded-full px-2 py-0.5"
            style={{ font: "var(--type-label)", color: tone, background: severityToken(rec.severity, true) }}
          >
            {SEVERITY_LABEL[rec.severity]}
          </span>
          <span
            style={{ font: "var(--type-label)", color: "var(--colour-ink-faint)" }}
          >
            {ruleLabel(rec.source_rule)}
          </span>
        </div>
        {pinned ? (
          <Tooltip content="Pinned in the resume viewer. Click again to unpin.">
            <span style={{ color: tone }}>
              <Pin size={13} fill="currentColor" />
            </span>
          </Tooltip>
        ) : null}
      </div>

      <h3 className="mt-2" style={{ font: "var(--type-title-sm)" }}>
        {rec.title}
      </h3>
      <p className="mt-1" style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-soft)" }}>
        {rec.rationale}
      </p>

      <p
        className="mt-2 flex items-start gap-1.5"
        style={{ font: "var(--type-body-sm)", color: "var(--colour-ink)" }}
      >
        <Target size={13} className="mt-[3px] shrink-0" style={{ color: "var(--colour-indigo)" }} />
        <span>{rec.action}</span>
      </p>

      {rec.evidence_text ? (
        <blockquote
          className="sunken mt-2.5 flex gap-2 px-2.5 py-2"
          style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}
        >
          <Quote size={12} className="mt-1 shrink-0" style={{ color: "var(--colour-ink-faint)" }} />
          <span>{truncate(rec.evidence_text, 190)}</span>
        </blockquote>
      ) : null}

      <div
        className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 border-t pt-2.5"
        style={{ borderColor: "var(--colour-hairline)" }}
      >
        {showScope ? <ScopeMeter present={scopePresent} compact /> : null}
        <Chip>{rec.section}</Chip>
        {rec.pillar && rec.pillar !== rec.section ? <Chip tone="indigo">{rec.pillar}</Chip> : null}
        <span
          className="data ml-auto"
          style={{ fontSize: 10.5, color: "var(--colour-ink-muted)" }}
        >
          {rec.expected_impact}
        </span>
        <EvidenceIndicator hasEvidence={hasEvidence} page={rec.evidence_refs[0]?.page} />
      </div>


    </article>
  );
}

function EvidenceIndicator({ hasEvidence, page }: { hasEvidence: boolean; page?: number }) {
  if (!hasEvidence) {
    return (
      <Tooltip content="This finding has no locatable text in the PDF, so nothing is highlighted.">
        <span
          tabIndex={0}
          className="inline-flex items-center gap-1"
          style={{ font: "var(--type-label)", color: "var(--colour-ink-faint)" }}
        >
          <CircleSlash size={11} /> No evidence location
        </span>
      </Tooltip>
    );
  }
  return (
    <Tooltip content={`Highlights on page ${page}. Click the card to pin it.`}>
      <span
        tabIndex={0}
        className="inline-flex items-center gap-1"
        style={{ font: "var(--type-label)", color: "var(--colour-indigo-deep)" }}
      >
        <MapPin size={11} /> Page {page}
      </span>
    </Tooltip>
  );
}

function EmptyRecommendations() {
  return (
    <div className="sunken mt-4 px-4 py-6 text-center">
      <p style={{ font: "var(--type-title-sm)" }}>No recommendations were returned</p>
      <p
        className="mx-auto mt-1 max-w-sm"
        style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}
      >
        The scoring service produced a result but no rule fired against it. Nothing is
        generated here to fill the gap.
      </p>
    </div>
  );
}
