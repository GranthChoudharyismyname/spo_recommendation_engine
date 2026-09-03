import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  FileText,
  Loader2,
  RefreshCw,
  Trash2,
  Upload,
} from "lucide-react";
import type { TrackCode, TrackDefinition } from "../lib/types";
import type { DashboardState, Phase } from "../lib/evaluationState";
import { PROGRESS_STEPS } from "../lib/evaluationState";
import { formatBytes } from "../lib/format";
import { Button, Chip, Panel } from "./primitives";

const MAX_BYTES_DEFAULT = 8 * 1024 * 1024;

export interface SetupPanelProps {
  state: DashboardState;
  tracks: TrackDefinition[];
  maxBytes: number;
  busy: boolean;
  canEvaluate: boolean;
  onFileAccepted: (file: File) => void;
  onFileRejected: (reason: string) => void;
  onFileCleared: () => void;
  onTrackChange: (track: TrackCode) => void;
  onEvaluate: () => void;
  onCancel: () => void;
}

export function EvaluationSetupPanel(props: SetupPanelProps) {
  const { state, tracks, maxBytes, busy, canEvaluate } = props;
  const track = tracks.find((t) => t.code === state.track);

  return (
    <Panel className="flex h-full flex-col overflow-hidden">
      <div className="scroll-area flex-1 p-5">
        <h2 style={{ font: "var(--type-title)" }}>Try out ResuMetr</h2>

        <div className="mt-5">
          {state.file ? (
            <SelectedFileCard
              file={state.file}
              pageCount={state.result?.file.page_count}
              onReplace={props.onFileAccepted}
              onRemove={props.onFileCleared}
              onRejected={props.onFileRejected}
              maxBytes={maxBytes}
              disabled={busy}
            />
          ) : (
            <ResumeDropzone
              maxBytes={maxBytes}
              disabled={busy}
              onAccepted={props.onFileAccepted}
              onRejected={props.onFileRejected}
            />
          )}
          {state.fileError ? (
            <p
              role="alert"
              className="mt-2 flex items-start gap-1.5"
              style={{ font: "var(--type-body-sm)", color: "var(--colour-critical)" }}
            >
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              {state.fileError}
            </p>
          ) : (
            <p className="mt-2" style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}>
              PDF only, up to {formatBytes(maxBytes)}.
            </p>
          )}
        </div>

        <div className="mt-6">
          <TrackSelector
            tracks={tracks}
            value={state.track}
            disabled={busy}
            evaluated={state.runsByTrack}
            onChange={props.onTrackChange}
          />
          {track ? (
            <div className="sunken mt-3 p-3">
              <p style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-soft)" }}>
                {track.description}
              </p>
            </div>
          ) : null}
        </div>
      </div>

      <div
        className="border-t p-5"
        style={{ borderColor: "var(--colour-hairline)", background: "var(--colour-glass-sunken)" }}
      >
        {busy ? (
          <>
            <EvaluationProgress phase={state.phase} stepIndex={state.stepIndex} />
            <div className="mt-3">
              <Button variant="ghost" full onClick={props.onCancel}>
                Cancel
              </Button>
            </div>
          </>
        ) : (
          <Button full onClick={props.onEvaluate} disabled={!canEvaluate} icon={<Check size={15} />}>
            {/* Saying "evaluate" over a result already on screen hides that the run
                replaces it. */}
            {state.runsByTrack[state.track] ? "Run this role again" : "Evaluate resume"}
          </Button>
        )}
      </div>
    </Panel>
  );
}

/* ---------------------------------------------------------------- Dropzone */

function validate(file: File, maxBytes: number): string | null {
  const isPdf =
    file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!isPdf) return `${file.name} is not a PDF. Only PDF resumes can be evaluated.`;
  if (file.size === 0) return `${file.name} is empty.`;
  if (file.size > maxBytes) {
    return `${file.name} is ${formatBytes(file.size)}. The maximum is ${formatBytes(maxBytes)}.`;
  }
  return null;
}

export function ResumeDropzone({
  maxBytes = MAX_BYTES_DEFAULT,
  disabled,
  onAccepted,
  onRejected,
}: {
  maxBytes?: number;
  disabled?: boolean;
  onAccepted: (file: File) => void;
  onRejected: (reason: string) => void;
}) {
  const [over, setOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handle = useCallback(
    (files: FileList | null) => {
      const file = files?.[0];
      if (!file) return;
      const problem = validate(file, maxBytes);
      if (problem) onRejected(problem);
      else onAccepted(file);
    },
    [maxBytes, onAccepted, onRejected],
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        if (!disabled) handle(e.dataTransfer.files);
      }}
      className="rounded-[var(--radius-md)] border border-dashed px-4 py-7 text-center transition-colors"
      style={{
        borderColor: over ? "var(--colour-indigo)" : "var(--colour-hairline-strong)",
        background: over ? "var(--colour-indigo-soft)" : "var(--colour-glass-sunken)",
        transitionDuration: "var(--motion-fast)",
      }}
    >
      <Upload
        size={20}
        className="mx-auto mb-2"
        style={{ color: over ? "var(--colour-indigo)" : "var(--colour-ink-faint)" }}
      />
      <p style={{ font: "var(--type-title-sm)" }}>Drop your resume here</p>
      <p className="mt-1" style={{ font: "var(--type-body-sm)", color: "var(--colour-ink-muted)" }}>
        or
      </p>
      <button
        type="button"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        className="mt-1 underline underline-offset-4"
        style={{ font: "var(--type-title-sm)", color: "var(--colour-indigo-deep)" }}
      >
        browse for a file
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        className="sr-only"
        onChange={(e) => {
          handle(e.target.files);
          e.target.value = "";
        }}
      />
    </div>
  );
}

/* ---------------------------------------------------------------- File card */

export function SelectedFileCard({
  file,
  pageCount,
  maxBytes,
  disabled,
  onReplace,
  onRemove,
  onRejected,
}: {
  file: File;
  pageCount?: number;
  maxBytes: number;
  disabled?: boolean;
  onReplace: (file: File) => void;
  onRemove: () => void;
  onRejected: (reason: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div className="card p-3">
      <div className="flex items-start gap-3">
        <div
          className="grid h-9 w-9 shrink-0 place-items-center rounded-[var(--radius-sm)]"
          style={{ background: "var(--colour-indigo-soft)", color: "var(--colour-indigo-deep)" }}
        >
          <FileText size={16} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate" style={{ font: "var(--type-title-sm)" }} title={file.name}>
            {file.name}
          </p>
          <p className="data mt-0.5" style={{ fontSize: 11, color: "var(--colour-ink-muted)" }}>
            {formatBytes(file.size)}
            {pageCount ? ` · ${pageCount} page${pageCount === 1 ? "" : "s"}` : ""}
          </p>
        </div>
        <Chip tone="strong" icon={<Check size={12} />}>
          PDF
        </Chip>
      </div>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={() => inputRef.current?.click()}
          className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] px-2 py-1 disabled:opacity-40"
          style={{ font: "var(--type-label)", color: "var(--colour-ink-soft)" }}
        >
          <RefreshCw size={12} /> Replace
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={onRemove}
          className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] px-2 py-1 disabled:opacity-40"
          style={{ font: "var(--type-label)", color: "var(--colour-critical)" }}
        >
          <Trash2 size={12} /> Remove
        </button>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        className="sr-only"
        onChange={(e) => {
          const next = e.target.files?.[0];
          e.target.value = "";
          if (!next) return;
          const problem = validate(next, maxBytes);
          if (problem) onRejected(problem);
          else onReplace(next);
        }}
      />
    </div>
  );
}

/* ---------------------------------------------------------------- Track selector */

export function TrackSelector({
  tracks,
  value,
  disabled,
  evaluated,
  onChange,
}: {
  tracks: TrackDefinition[];
  value: TrackCode;
  disabled?: boolean;
  /** Roles already evaluated for the loaded PDF, so a kept result is visible up front. */
  evaluated?: DashboardState["runsByTrack"];
  onChange: (track: TrackCode) => void;
}) {
  return (
    <fieldset disabled={disabled} className="min-w-0">
      <legend className="eyebrow mb-2">Target role</legend>
      <div role="radiogroup" aria-label="Target role" className="grid gap-1.5">
        {tracks.map((track) => {
          const selected = track.code === value;
          return (
            <button
              key={track.code}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onChange(track.code)}
              className="flex items-center gap-2.5 rounded-[var(--radius-md)] px-3 py-2.5 text-left transition-colors disabled:opacity-50"
              style={{
                background: selected ? "var(--colour-indigo-soft)" : "var(--colour-glass-sunken)",
                border: `1px solid ${selected ? "var(--colour-indigo)" : "var(--colour-hairline)"}`,
                transitionDuration: "var(--motion-fast)",
              }}
            >
              <span
                aria-hidden
                className="grid h-3.5 w-3.5 shrink-0 place-items-center rounded-full"
                style={{
                  border: `1.5px solid ${selected ? "var(--colour-indigo)" : "var(--colour-hairline-strong)"}`,
                }}
              >
                {selected ? (
                  <span
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ background: "var(--colour-indigo)" }}
                  />
                ) : null}
              </span>
              {/* Name only. The full description sits in the card below the selector,
                  so repeating it here just crowds the rail. */}
              <span
                className="min-w-0 flex-1 truncate"
                style={{
                  font: "var(--type-title-sm)",
                  color: selected ? "var(--colour-indigo-deep)" : "var(--colour-ink)",
                }}
                title={track.label}
              >
                {track.short_label}
              </span>
              {/* A score here means this role has already been run on this PDF and
                  selecting it shows that result rather than starting again. */}
              {evaluated?.[track.code] ? (
                <span
                  className="shrink-0 tabular-nums"
                  style={{ font: "var(--type-label)", color: "var(--colour-ink-faint)" }}
                  title="Already evaluated — selecting this role shows the saved result"
                >
                  {evaluated[track.code]!.result.overall_score}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

/* ---------------------------------------------------------------- Progress */

export function EvaluationProgress({
  phase,
  stepIndex,
}: {
  phase: Phase;
  stepIndex: number;
}) {
  // The step list advances on a timer while a single request is in flight, so it is
  // labelled as an estimate rather than presented as server-reported progress.
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => window.clearInterval(id);
  }, []);

  return (
    <div aria-live="polite">
      <div className="mb-2 flex items-baseline justify-between">
        <p className="eyebrow">Evaluating</p>
        <span className="data" style={{ fontSize: 10.5, color: "var(--colour-ink-faint)" }}>
          {elapsed}s
        </span>
      </div>
      <ol className="grid gap-1.5">
        {PROGRESS_STEPS.map((step, index) => {
          const done = index < stepIndex;
          const current = index === stepIndex && phase !== "complete";
          return (
            <li key={step.label} className="flex items-center gap-2">
              <span className="grid h-4 w-4 shrink-0 place-items-center">
                {done ? (
                  <Check size={12} style={{ color: "var(--colour-strong)" }} />
                ) : current ? (
                  <Loader2
                    size={12}
                    className="animate-spin"
                    style={{ color: "var(--colour-indigo)" }}
                  />
                ) : (
                  <span
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ background: "var(--colour-hairline-strong)" }}
                  />
                )}
              </span>
              <span
                style={{
                  font: "var(--type-body-sm)",
                  color: done || current ? "var(--colour-ink-soft)" : "var(--colour-ink-faint)",
                }}
              >
                {step.label}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
