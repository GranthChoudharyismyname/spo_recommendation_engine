import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PanelRightClose, PanelRightOpen, SlidersHorizontal } from "lucide-react";
import * as Tabs from "@radix-ui/react-tabs";

import {
  ApiError,
  NetworkError,
  TimeoutError,
  USE_MOCK,
  evaluateResume,
  fetchHealth,
} from "../lib/api";
import { MalformedResponseError } from "../lib/validate";
import { PROGRESS_STEPS, useDashboardState } from "../lib/evaluationState";
import type { FailureState } from "../lib/evaluationState";
import type { HealthResponse, TrackCode, TrackDefinition } from "../lib/types";
import { BREAKPOINT_MOBILE, BREAKPOINT_TABLET, useMediaQuery } from "../hooks/useMediaQuery";

import { DashboardHeader } from "./DashboardHeader";
import { useTheme } from "../lib/theme";
import { useColumnWidths, useFolding, RAIL_BOUNDS, VIEWER_BOUNDS } from "../lib/workspace";
import { ResizeHandle } from "./ResizeHandle";
import { FoldContext } from "./primitives";
import { EvaluationSetupPanel } from "./EvaluationSetupPanel";
import { ScoreOverview } from "./ScoreOverview";
import { RecommendationList } from "./RecommendationList";
import { PillarBreakdown } from "./PillarBreakdown";
import { CompanyFitPanel } from "./CompanyFitPanel";
import { AgentRecommendationPanel } from "./AgentRecommendationPanel";
import { ImpactPanel } from "./ImpactPanel";
import { DocumentLayoutPanel } from "./DocumentLayoutPanel";
import { DiagnosticReportPanel } from "./DiagnosticReportPanel";
import { EvaluatingState } from "./EvaluatingState";
import { ReviewNotice } from "./ValidationStatus";
import { ResumeEvidenceViewer } from "./ResumeEvidenceViewer";
import {
  CompliancePanel,
  DegradedBanner,
  FixtureNotice,
  FailurePanel,
  ResultsPlaceholder,
} from "./Notices";
import { Button, TooltipProvider } from "./primitives";

const TRACKS: TrackDefinition[] = [
  {
    code: "ANALYST_AIML",
    label: "Analytics, Data Science & Applied AI/ML",
    short_label: "Analytics & AI/ML",
    description:
      "Weights work experience and ML project depth equally; statistical and model metrics carry the SCOPE pillar.",
    project_pillar_label: "Projects & ML Depth",
    kg_role: "ANALYST",
  },
  {
    code: "CONSULT_PM",
    label: "Management Consulting & Product Management",
    short_label: "Consulting & PM",
    description:
      "Leadership and positions of responsibility carry the heaviest single weight, tied with work experience.",
    project_pillar_label: "Projects & Strategic Initiatives",
    kg_role: "CONSULT",
  },
  {
    code: "CORE_TECHNOM",
    label: "Core Engineering, Supply Chain & Techno-Management",
    short_label: "Core & Techno-Mgmt",
    description:
      "Branch match and ground-level PoR weigh heavily; coursework is folded into the SCOPE pillar.",
    project_pillar_label: "Core Projects & Research Pedigree",
    kg_role: "CORE",
  },
  {
    code: "QUANT",
    label: "Quantitative Finance & High-Frequency Trading",
    short_label: "Quant & HFT",
    description:
      "Academics and CPI dominate at 35%; mathematical and systems depth is the second pillar.",
    project_pillar_label: "Projects & Technical/Math Depth",
    kg_role: "QUANT",
  },
  {
    code: "SDE",
    label: "Software Development Engineering & Systems",
    short_label: "Software Engineering",
    description:
      "Work experience leads, with systems depth, academics and branch match close behind.",
    project_pillar_label: "Projects & Systems Depth",
    kg_role: "SDE",
  },
];

const DEFAULT_MAX_BYTES = 8 * 1024 * 1024;

const MOBILE_TABS = [
  { value: "setup", label: "Setup" },
  { value: "results", label: "Results" },
  { value: "resume", label: "Resume" },
] as const;

export function ResumeDashboard() {
  const { state, dispatch, focusedRecommendation, setActive, togglePin } = useDashboardState();
  const [tracks, setTracks] = useState<TrackDefinition[]>(TRACKS);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [mobileTab, setMobileTab] = useState("setup");
  const [railOpen, setRailOpen] = useState(true);
  const theme = useTheme();
  const fold = useFolding();
  const columns = useColumnWidths();
  const [viewerOpen, setViewerOpen] = useState(true);

  const abortRef = useRef<AbortController | null>(null);
  const timersRef = useRef<number[]>([]);
  const objectUrlRef = useRef<string | null>(null);

  const isTablet = useMediaQuery(BREAKPOINT_TABLET);
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);

  const busy = ["uploading", "parsing", "scoring"].includes(state.phase);
  const maxBytes = health?.limits.max_upload_bytes ?? DEFAULT_MAX_BYTES;

  /* ---- capability probe ------------------------------------------------- */
  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal)
      .then(setHealth)
      .catch(() => setHealth(null));
    // The track list is served by the API so the weights cannot drift from the scorer;
    // the built-in list is the fallback when the service is not up yet.
    fetch("/api/tracks", { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((body) => {
        if (body?.tracks?.length) setTracks(body.tracks as TrackDefinition[]);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  /* ---- object URL lifetime ---------------------------------------------- */
  const revoke = useCallback(() => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
  }, []);
  useEffect(() => revoke, [revoke]);

  const clearTimers = useCallback(() => {
    timersRef.current.forEach(window.clearTimeout);
    timersRef.current = [];
  }, []);

  const handleFile = useCallback(
    (file: File) => {
      revoke();
      const url = URL.createObjectURL(file);
      objectUrlRef.current = url;
      dispatch({ type: "file/selected", file, url });
      if (isMobile) setMobileTab("setup");
    },
    [dispatch, isMobile, revoke],
  );

  const handleClear = useCallback(() => {
    revoke();
    clearTimers();
    dispatch({ type: "file/cleared" });
  }, [clearTimers, dispatch, revoke]);

  const runEvaluation = useCallback(async () => {
    if (!state.file) return;
    clearTimers();
    dispatch({ type: "run/started" });

    // The API answers once, so the step list is paced locally and labelled as an
    // estimate. It never claims a stage the server has actually reported.
    PROGRESS_STEPS.forEach((_, index) => {
      if (index === 0) return;
      timersRef.current.push(
        window.setTimeout(() => dispatch({ type: "run/step", index }), index * 1400),
      );
    });

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const result = await evaluateResume({
        file: state.file,
        track: state.track,
        signal: controller.signal,
      });
      clearTimers();
      dispatch({ type: "run/succeeded", result });
      if (isMobile) setMobileTab("results");
    } catch (error) {
      clearTimers();
      if (error instanceof Error && error.name === "AbortError") {
        dispatch({ type: "run/cancelled" });
        return;
      }
      dispatch({ type: "run/failed", failure: toFailure(error) });
    } finally {
      abortRef.current = null;
    }
  }, [clearTimers, dispatch, isMobile, state.file, state.track]);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    clearTimers();
  }, [clearTimers]);

  /* ---- recommendation -> evidence --------------------------------------- */
  const handlePin = useCallback(
    (id: string) => {
      togglePin(id);
      // On mobile the viewer is a separate tab, so pinning has to take the reader there.
      if (isMobile) setMobileTab("resume");
      else if (isTablet) setViewerOpen(true);
    },
    [isMobile, isTablet, togglePin],
  );

  const canEvaluate = Boolean(state.file) && !busy && (USE_MOCK || health?.capabilities.gemini_configured !== false);

  const setup = (
    <EvaluationSetupPanel
      state={state}
      tracks={tracks}
      maxBytes={maxBytes}
      busy={busy}
      canEvaluate={canEvaluate}
      onFileAccepted={handleFile}
      onFileRejected={(reason) => dispatch({ type: "file/rejected", reason })}
      onFileCleared={handleClear}
      onTrackChange={(track: TrackCode) => dispatch({ type: "track/changed", track })}
      onEvaluate={runEvaluation}
      onCancel={cancel}
    />
  );

  const results = useMemo(() => {
    if (busy) return <EvaluatingState stepIndex={state.stepIndex} />;
    if (state.phase === "error" && state.failure) {
      return <FailurePanel failure={state.failure} onRetry={runEvaluation} />;
    }
    if (!state.result) {
      return (
        <>
          {health && !health.capabilities.gemini_configured && !USE_MOCK ? (
            <DegradedBanner
              title="Evaluations cannot run — the scoring service is not configured"
              warnings={[
                {
                  code: "SCORING_UNAVAILABLE",
                  message:
                    "The scoring service has no model key configured, so evaluations cannot run. Set GEMINI_API_KEY on the API and restart it.",
                },
              ]}
            />
          ) : null}
          <ResultsPlaceholder />
        </>
      );
    }
    const result = state.result;

    return (
      <>
        {result.mockNotes?.length ? <FixtureNotice notes={result.mockNotes} /> : null}
        {/* A critical finding is flagged above the score, never in place of it. */}
        {result.validation ? <ReviewNotice report={result.validation} /> : null}
        <DegradedBanner warnings={result.warnings} />
        <ScoreOverview result={result} />
        {result.report ? <DiagnosticReportPanel report={result.report} /> : null}
        {result.agent_recommendations ? (
          <AgentRecommendationPanel agent={result.agent_recommendations} />
        ) : null}
        <RecommendationList
          recommendations={result.recommendations}
          ruleset={result.derived.recommendations}
          activeId={state.activeRecommendationId}
          pinnedId={state.pinnedRecommendationId}
          onActivate={setActive}
          onPin={handlePin}
        />
        <PillarBreakdown result={result} />
        {result.structural_breakdown ? (
          <DocumentLayoutPanel
            breakdown={result.structural_breakdown}
            visual={result.structural_visual}
          />
        ) : null}
        {result.extracted_signals.quantified_results_summary ? (
          <ImpactPanel
            results={result.extracted_signals.quantified_results ?? []}
            summary={result.extracted_signals.quantified_results_summary}
          />
        ) : null}
        <CompanyFitPanel fit={result.company_fit} />
        <CompliancePanel compliance={result.compliance} />
      </>
    );
  }, [
    busy,
    state.stepIndex,
    handlePin,
    health,
    runEvaluation,
    setActive,
    state.activeRecommendationId,
    state.failure,
    state.phase,
    state.pinnedRecommendationId,
    state.result,
  ]);

  const viewer = (
    <ResumeEvidenceViewer
      fileUrl={state.fileUrl}
      fileName={state.file?.name ?? null}
      focused={focusedRecommendation}
      pinnedId={state.pinnedRecommendationId}
      scale={state.pdfScale}
      fitWidth={state.fitWidth}
      page={state.pdfPage}
      onPageChange={(page) => dispatch({ type: "pdf/page", page })}
      onScaleChange={(scale) => dispatch({ type: "pdf/scale", scale })}
      onFitWidth={(on) => dispatch({ type: "pdf/fitWidth", on })}
    />
  );

  return (
    <TooltipProvider>
      <FoldContext.Provider value={fold}>
      <div className="flex min-h-full flex-col">
        <DashboardHeader
          mock={USE_MOCK || state.result?.meta.is_mock === true}
          theme={theme.choice}
          onThemeChange={theme.setChoice}
        />

        {isMobile ? (
          <Tabs.Root value={mobileTab} onValueChange={setMobileTab} className="flex flex-1 flex-col">
            <Tabs.List
              className="glass sticky z-20 flex gap-1 p-1"
              style={{
                top: "var(--header-height)",
                borderRadius: 0,
                borderWidth: "0 0 1px",
                borderColor: "var(--colour-hairline)",
              }}
            >
              {MOBILE_TABS.map(({ value, label }) => (
                <Tabs.Trigger
                  key={value}
                  value={value}
                  className="flex-1 rounded-[var(--radius-sm)] px-3 py-2 transition-colors
                    text-[color:var(--colour-ink-muted)]
                    data-[state=active]:bg-[var(--colour-indigo-soft)]
                    data-[state=active]:text-[color:var(--colour-indigo-deep)]
                    data-[state=active]:shadow-[var(--shadow-flat)]"
                  style={{ font: "var(--type-title-sm)", transitionDuration: "var(--motion-fast)" }}
                >
                  {label}
                </Tabs.Trigger>
              ))}
            </Tabs.List>
            <Tabs.Content value="setup" className="flex-1 p-3">
              <div className="min-h-[70vh]">{setup}</div>
            </Tabs.Content>
            <Tabs.Content value="results" className="grid flex-1 gap-3 p-3">
              {results}
            </Tabs.Content>
            <Tabs.Content value="resume" className="flex-1 p-3">
              <div className="h-[80vh]">{viewer}</div>
            </Tabs.Content>
          </Tabs.Root>
        ) : (
          <div className="flex flex-1 gap-4 p-4">
            {railOpen ? (
              <>
                <aside
                  className="shrink-0"
                  style={{
                    width: columns.widths.rail,
                    position: "sticky",
                    top: "calc(var(--header-height) + 16px)",
                    height: "calc(100vh - var(--header-height) - 32px)",
                  }}
                >
                  {setup}
                </aside>
                <ResizeHandle
                  value={columns.widths.rail}
                  min={RAIL_BOUNDS.min}
                  max={RAIL_BOUNDS.max}
                  edge="left"
                  label="Resize the setup column"
                  onChange={(v) => columns.set("rail", v)}
                  onNudge={(d) => columns.nudge("rail", d)}
                  onReset={columns.reset}
                />
              </>
            ) : null}

            <main className="min-w-0 flex-1">
              {isTablet ? (
                <div className="mb-3 flex gap-2">
                  <Button
                    variant="ghost"
                    onClick={() => setRailOpen((open) => !open)}
                    icon={<SlidersHorizontal size={14} />}
                  >
                    {railOpen ? "Hide setup" : "Show setup"}
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => setViewerOpen((open) => !open)}
                    icon={viewerOpen ? <PanelRightClose size={14} /> : <PanelRightOpen size={14} />}
                  >
                    {viewerOpen ? "Hide resume" : "Show resume"}
                  </Button>
                </div>
              ) : null}
              <div className="grid gap-4">{results}</div>
            </main>

            {viewerOpen ? (
              <>
                <ResizeHandle
                  value={columns.widths.viewer}
                  min={VIEWER_BOUNDS.min}
                  max={VIEWER_BOUNDS.max}
                  edge="right"
                  label="Resize the resume column"
                  onChange={(v) => columns.set("viewer", v)}
                  onNudge={(d) => columns.nudge("viewer", d)}
                  onReset={columns.reset}
                />
                <aside
                  className="shrink-0"
                  style={{
                    width: columns.widths.viewer,
                    position: "sticky",
                    top: "calc(var(--header-height) + 16px)",
                    height: "calc(100vh - var(--header-height) - 32px)",
                  }}
                >
                  {viewer}
                </aside>
              </>
            ) : null}
          </div>
        )}
      </div>
      </FoldContext.Provider>
    </TooltipProvider>
  );
}

function toFailure(error: unknown): FailureState {
  if (error instanceof MalformedResponseError) {
    return {
      code: "MALFORMED_RESPONSE",
      title: "The service returned an unusable result",
      message:
        "The response reached the browser but did not match the evaluation contract, so nothing was rendered from it.",
      problems: error.problems,
      retryable: true,
    };
  }
  if (error instanceof TimeoutError) {
    return {
      code: "TIMEOUT",
      title: "The evaluation timed out",
      message: error.message,
      retryable: true,
    };
  }
  if (error instanceof NetworkError) {
    return {
      code: "NETWORK",
      title: "The evaluation service is unreachable",
      message: `${error.message} Start it with \`python run_api.py\` from the backend directory, then try again.`,
      retryable: true,
    };
  }
  if (error instanceof ApiError) {
    const titles: Record<string, string> = {
      SCORING_UNAVAILABLE: "The scoring service has no model key",
      SCORING_FAILED: "The scoring engine could not complete",
      RATE_LIMITED: "The model quota is exhausted",
      MALFORMED_RESULT: "The scoring engine returned an incomplete result",
      FILE_TOO_LARGE: "That PDF is too large",
      NOT_A_PDF: "That file is not a PDF",
      EMPTY_FILE: "That file is empty",
      INVALID_TRACK: "That role is not recognised",
    };
    return {
      code: error.code,
      title: titles[error.code] ?? "The evaluation failed",
      message: error.message,
      retryable: error.status >= 500 || error.code === "SCORING_FAILED",
    };
  }
  return {
    code: "UNKNOWN",
    title: "The evaluation failed",
    message: error instanceof Error ? error.message : "An unexpected error occurred.",
    retryable: true,
  };
}
