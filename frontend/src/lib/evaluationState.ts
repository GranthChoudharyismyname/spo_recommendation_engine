/**
 * Shared dashboard state.
 *
 * Recommendation cards and PDF highlights address each other by recommendation id, so
 * hover, keyboard focus, pinning and the viewer's page position all resolve from one
 * place and stay deterministic.
 */

import { useCallback, useMemo, useReducer } from "react";
import type { EvaluationResult, EvidenceRef, Recommendation, TrackCode } from "./types";

export type Phase =
  | "idle"
  | "file-selected"
  | "uploading"
  | "parsing"
  | "scoring"
  | "complete"
  | "error";

export const PROGRESS_STEPS = [
  { phase: "uploading", label: "Uploading PDF" },
  { phase: "parsing", label: "Reading structure" },
  { phase: "parsing", label: "Extracting resume sections" },
  { phase: "scoring", label: "Evaluating role fit" },
  { phase: "scoring", label: "Preparing results" },
] as const;

export interface FailureState {
  code: string;
  title: string;
  message: string;
  problems?: string[];
  retryable: boolean;
}

/**
 * A finished evaluation, kept so that returning to a role shows what was already run.
 *
 * The pinned recommendation and page travel with it: switching back should land where
 * the reader left off, not at the top of a rebuilt result.
 */
export interface CachedRun {
  result: EvaluationResult;
  pinnedRecommendationId: string | null;
  pdfPage: number;
}

export interface DashboardState {
  phase: Phase;
  file: File | null;
  fileUrl: string | null;
  fileError: string | null;
  track: TrackCode;
  result: EvaluationResult | null;
  failure: FailureState | null;
  stepIndex: number;
  activeRecommendationId: string | null;
  pinnedRecommendationId: string | null;
  pdfPage: number;
  pdfScale: number;
  fitWidth: boolean;
  /**
   * Completed runs for the document currently loaded, by role.
   *
   * Each role weights the pillars differently, so its result is genuinely its own — but
   * that makes it worth keeping, not worth discarding. Comparing roles is the reason to
   * switch in the first place, and re-running costs a minute and six model calls.
   * Cleared whenever the document changes, since a result belongs to one PDF.
   */
  runsByTrack: Partial<Record<TrackCode, CachedRun>>;
}

type Action =
  | { type: "file/selected"; file: File; url: string }
  | { type: "file/rejected"; reason: string }
  | { type: "file/cleared" }
  | { type: "track/changed"; track: TrackCode }
  | { type: "run/started" }
  | { type: "run/step"; index: number }
  | { type: "run/succeeded"; result: EvaluationResult }
  | { type: "run/failed"; failure: FailureState }
  | { type: "run/cancelled" }
  | { type: "rec/hovered"; id: string | null }
  | { type: "rec/pinned"; id: string | null }
  | { type: "pdf/page"; page: number }
  | { type: "pdf/scale"; scale: number }
  | { type: "pdf/fitWidth"; on: boolean };

export const initialState: DashboardState = {
  phase: "idle",
  file: null,
  fileUrl: null,
  fileError: null,
  track: "SDE",
  result: null,
  failure: null,
  stepIndex: 0,
  activeRecommendationId: null,
  pinnedRecommendationId: null,
  pdfPage: 1,
  pdfScale: 1,
  fitWidth: true,
  runsByTrack: {},
};

/**
 * Mirror a change into the current role's cached run.
 *
 * The cache is a snapshot taken when the run finished; without this, anything the reader
 * did afterwards — pinning a recommendation, turning to another page — would be lost the
 * moment they switched roles, which is exactly the case the cache exists to serve.
 */
function syncCache(
  state: DashboardState,
  patch: Partial<CachedRun>,
): DashboardState["runsByTrack"] {
  const current = state.runsByTrack[state.track];
  if (!current) return state.runsByTrack;
  return { ...state.runsByTrack, [state.track]: { ...current, ...patch } };
}

function reducer(state: DashboardState, action: Action): DashboardState {
  switch (action.type) {
    case "file/selected":
      return {
        ...state,
        phase: "file-selected",
        file: action.file,
        fileUrl: action.url,
        fileError: null,
        // A new document invalidates the previous evaluation and every highlight in it,
        // for every role — the cache is keyed to the PDF that produced it.
        result: null,
        failure: null,
        activeRecommendationId: null,
        pinnedRecommendationId: null,
        pdfPage: 1,
        runsByTrack: {},
      };
    case "file/rejected":
      return { ...state, fileError: action.reason };
    case "file/cleared":
      return {
        ...initialState,
        track: state.track,
      };
    case "track/changed": {
      if (state.track === action.track) return state;
      // A result already produced for the incoming role is shown again rather than
      // thrown away; only a role with nothing yet returns to the pre-run state.
      const cached = state.runsByTrack[action.track];
      return {
        ...state,
        track: action.track,
        failure: null,
        activeRecommendationId: null,
        result: cached ? cached.result : null,
        pinnedRecommendationId: cached ? cached.pinnedRecommendationId : null,
        pdfPage: cached ? cached.pdfPage : 1,
        phase: cached ? "complete" : state.file ? "file-selected" : "idle",
        stepIndex: cached ? PROGRESS_STEPS.length : 0,
      };
    }
    case "run/started":
      return { ...state, phase: "uploading", stepIndex: 0, failure: null, result: null };
    case "run/step": {
      const step = PROGRESS_STEPS[action.index];
      return step ? { ...state, stepIndex: action.index, phase: step.phase } : state;
    }
    case "run/succeeded":
      return {
        ...state,
        phase: "complete",
        result: action.result,
        failure: null,
        stepIndex: PROGRESS_STEPS.length,
        runsByTrack: {
          ...state.runsByTrack,
          [state.track]: {
            result: action.result,
            pinnedRecommendationId: null,
            pdfPage: 1,
          },
        },
      };
    case "run/failed":
      return { ...state, phase: "error", failure: action.failure, result: null };

    case "run/cancelled":
      return { ...state, phase: state.file ? "file-selected" : "idle", stepIndex: 0 };
    case "rec/hovered":
      return state.activeRecommendationId === action.id
        ? state
        : { ...state, activeRecommendationId: action.id };
    case "rec/pinned": {
      // Clicking the pinned card unpins it; clicking another moves the pin.
      const next = state.pinnedRecommendationId === action.id ? null : action.id;
      return {
        ...state,
        pinnedRecommendationId: next,
        activeRecommendationId: next ?? state.activeRecommendationId,
        runsByTrack: syncCache(state, { pinnedRecommendationId: next }),
      };
    }
    case "pdf/page":
      return state.pdfPage === action.page
        ? state
        : { ...state, pdfPage: action.page, runsByTrack: syncCache(state, { pdfPage: action.page }) };
    case "pdf/scale":
      return { ...state, pdfScale: action.scale, fitWidth: false };
    case "pdf/fitWidth":
      return { ...state, fitWidth: action.on };
    default:
      return state;
  }
}

export function useDashboardState() {
  const [state, dispatch] = useReducer(reducer, initialState);

  /** The recommendation whose evidence the viewer should currently show. */
  const focusedRecommendation: Recommendation | null = useMemo(() => {
    const id = state.pinnedRecommendationId ?? state.activeRecommendationId;
    if (!id || !state.result) return null;
    return state.result.recommendations.find((r) => r.id === id) ?? null;
  }, [state.pinnedRecommendationId, state.activeRecommendationId, state.result]);

  const activeEvidenceRefs: EvidenceRef[] = focusedRecommendation?.evidence_refs ?? [];

  const setActive = useCallback((id: string | null) => {
    dispatch({ type: "rec/hovered", id });
  }, []);

  const togglePin = useCallback((id: string) => {
    dispatch({ type: "rec/pinned", id });
  }, []);

  return { state, dispatch, focusedRecommendation, activeEvidenceRefs, setActive, togglePin };
}

export type DashboardDispatch = ReturnType<typeof useDashboardState>["dispatch"];
