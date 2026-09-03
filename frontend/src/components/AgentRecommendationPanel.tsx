/**
 * Phase 3 output — the agent-authored recommendations.
 *
 * Kept visually distinct from the deterministic rule findings, because they are produced
 * differently and carry different guarantees. Each item names the rule it sharpened, and
 * the rejected drafts stay visible: an agent that silently discards its own output cannot
 * be audited, and the rejections are the evidence that the self-critique pass ran.
 */

import { useState } from "react";
import { ChevronDown, Quote, ShieldCheck, Target, TrendingUp, XCircle } from "lucide-react";
import type { AgentRecommendations, Severity } from "../lib/types";
import { SEVERITY_LABEL, SEVERITY_ORDER, ruleLabel, severityToken } from "../lib/format";
import { Chip, Panel, SectionHeader, Tooltip } from "./primitives";

export function AgentRecommendationPanel({
  agent,
  onHoverEvidence,
}: {
  agent: AgentRecommendations;
  /** Lets an agent item drive the same PDF highlight as a rule card. */
  onHoverEvidence?: (text: string | null) => void;
}) {
  const [showRejected, setShowRejected] = useState(false);
  const { attribution, counts } = agent;

  const ordered = [...agent.recommendations].sort(
    (a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity),
  );

  return (
    <Panel foldId="agent" className="p-5">
      <SectionHeader
        title="Review"
        eyebrow="Grounded in your resume"
        meta={
          <Tooltip
            content={`${counts.drafted} drafted, ${counts.kept} kept, ${counts.rejected} rejected by the self-critique pass (${counts.rejected_by_code} by hard rule).`}
          >
            <span tabIndex={0}>
              <Chip tone="indigo" icon={<ShieldCheck size={11} />}>
                {counts.kept} of {counts.drafted} kept
              </Chip>
            </span>
          </Tooltip>
        }
      />

      {attribution.next_band ? (
        <div
          className="mt-4 flex items-start gap-2.5 rounded-[var(--radius-md)] px-3.5 py-3"
          style={{ background: "var(--colour-indigo-soft)" }}
        >
          <TrendingUp
            size={15}
            className="mt-0.5 shrink-0"
            style={{ color: "var(--colour-indigo-deep)" }}
          />
          <p style={{ font: "var(--type-body-sm)", color: "var(--colour-ink)" }}>
            <strong className="data">{attribution.next_band.points_needed}</strong> points
            below <strong>{attribution.next_band.label}</strong> (threshold{" "}
            <span className="data">{attribution.next_band.threshold}</span>).{" "}
            <span style={{ color: "var(--colour-ink-muted)" }}>
              {attribution.total_available.toFixed(1)} points remain available across all
              pillars.
            </span>
          </p>
        </div>
      ) : null}

      {ordered.length === 0 ? (
        <p
          className="mt-4"
          style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}
        >
          The agent produced no recommendations that survived its own critique pass. Nothing
          is shown in their place.
        </p>
      ) : (
        <ul className="mt-4 grid gap-2.5">
          {ordered.map((item) => {
            const tone = severityToken(item.severity as Severity);
            return (
              <li key={item.id}>
                <article
                  className="card p-3.5"
                  style={{ borderLeft: `3px solid ${tone}` }}
                  onMouseEnter={() => onHoverEvidence?.(item.evidence_ref || null)}
                  onMouseLeave={() => onHoverEvidence?.(null)}
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span
                      className="rounded-full px-2 py-0.5"
                      style={{
                        font: "var(--type-label)",
                        color: tone,
                        background: severityToken(item.severity as Severity, true),
                      }}
                    >
                      {SEVERITY_LABEL[item.severity as Severity]}
                    </span>
                    <span style={{ font: "var(--type-label)", color: "var(--colour-ink-faint)" }}>
                      {ruleLabel(item.source_rule)}
                    </span>
                  </div>

                  <h3 className="mt-2" style={{ font: "var(--type-title-sm)" }}>
                    {item.issue}
                  </h3>

                  {item.evidence_ref ? (
                    <blockquote
                      className="sunken mt-2 flex gap-2 px-2.5 py-2"
                      style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}
                    >
                      <Quote
                        size={12}
                        className="mt-1 shrink-0"
                        style={{ color: "var(--colour-ink-faint)" }}
                      />
                      <span>{item.evidence_ref}</span>
                    </blockquote>
                  ) : null}

                  <p
                    className="mt-2 flex items-start gap-1.5"
                    style={{ font: "var(--type-body-sm)", color: "var(--colour-ink)" }}
                  >
                    <Target
                      size={13}
                      className="mt-[3px] shrink-0"
                      style={{ color: "var(--colour-indigo)" }}
                    />
                    <span>{item.suggested_action}</span>
                  </p>

                  <div
                    className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 border-t pt-2.5"
                    style={{ borderColor: "var(--colour-hairline)" }}
                  >
                    {item.section ? <Chip>{item.section}</Chip> : null}
                    {item.pillar && item.pillar !== item.section ? (
                      <Chip tone="indigo">{item.pillar}</Chip>
                    ) : null}
                    {item.expected_impact ? (
                      <span
                        className="data ml-auto"
                        style={{ fontSize: 10.5, color: "var(--colour-ink-muted)" }}
                      >
                        {item.expected_impact}
                      </span>
                    ) : null}
                  </div>
                </article>
              </li>
            );
          })}
        </ul>
      )}

      {agent.rejected.length > 0 ? (
        <>
          <button
            type="button"
            onClick={() => setShowRejected((v) => !v)}
            aria-expanded={showRejected}
            className="mt-4 flex w-full items-center justify-between rounded-[var(--radius-sm)] py-1"
            style={{ font: "var(--type-title-sm)", color: "var(--colour-ink-muted)" }}
          >
            <span>
              {showRejected ? "Hide" : "Show"} {agent.rejected.length} draft
              {agent.rejected.length === 1 ? "" : "s"} the critique pass rejected
            </span>
            <ChevronDown
              size={15}
              style={{
                transform: showRejected ? "rotate(180deg)" : "none",
                transition: "transform var(--motion-fast) var(--ease-out)",
              }}
            />
          </button>
          {showRejected ? (
            <ul className="mt-2 grid gap-2">
              {agent.rejected.map((item, index) => (
                <li
                  key={`${item.id}-${index}`}
                  className="sunken px-3 py-2.5"
                  style={{ opacity: 0.85 }}
                >
                  <div className="flex items-start gap-2">
                    <XCircle
                      size={13}
                      className="mt-0.5 shrink-0"
                      style={{ color: "var(--colour-critical)" }}
                    />
                    <div className="min-w-0">
                      <p
                        style={{
                          font: "var(--type-body-sm)",
                          color: "var(--colour-ink-soft)",
                          textDecoration: "line-through",
                        }}
                      >
                        {item.issue || item.suggested_action}
                      </p>
                      <p
                        className="mt-1"
                        style={{ font: "var(--type-body-sm)", color: "var(--colour-critical)" }}
                      >
                        {item.rejection_reason}
                      </p>
                      <span
                        className="mt-1 inline-block"
                        style={{ font: "var(--type-label)", color: "var(--colour-ink-faint)" }}
                      >
                        Removed in review
                      </span>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </Panel>
  );
}
