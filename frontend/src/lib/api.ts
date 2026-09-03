/**
 * The only module that talks to the network.
 *
 * The mock service is a separate module and is reachable only through the explicit
 * VITE_USE_MOCK switch below. Production responses and fixture data never mix inside
 * a single result: whichever path runs, `meta.is_mock` says which one it was.
 */

import type { ApiErrorBody, EvaluationResult, HealthResponse, TrackCode } from "./types";
import { MalformedResponseError, validateEvaluation } from "./validate";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "";
export const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true";

// A full evaluation makes six model calls and runs 60-180s. Browsers do not time out
// fetches by default, but an explicit ceiling turns a hung backend into a clear message
// instead of a spinner that never resolves.
const EVALUATE_TIMEOUT_MS = 300_000;


export class TimeoutError extends Error {
  constructor() {
    super(
      "The evaluation did not finish within five minutes. The scoring service may be " +
        "stuck or rate-limited; check its logs and try again.",
    );
    this.name = "TimeoutError";
  }
}


export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly detail: Record<string, unknown>;
  constructor(status: number, code: string, message: string, detail: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

export class NetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NetworkError";
  }
}

async function readError(response: Response): Promise<ApiError> {
  let code = `HTTP_${response.status}`;
  let message = `The service responded with ${response.status}.`;
  let detail: Record<string, unknown> = {};
  try {
    const body = (await response.json()) as Partial<ApiErrorBody>;
    if (body?.error) {
      const { code: c, message: m, ...rest } = body.error;
      if (typeof c === "string") code = c;
      if (typeof m === "string") message = m;
      detail = rest;
    }
  } catch {
    // A non-JSON error body is still an error; the status-derived message stands.
  }
  return new ApiError(response.status, code, message, detail);
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  if (USE_MOCK) {
    const { mockHealth } = await import("../mocks/mockService");
    return mockHealth();
  }
  let response: Response;
  try {
    response = await fetch(`${BASE}/api/health`, { signal });
  } catch (error) {
    throw new NetworkError(
      error instanceof Error && error.name === "AbortError"
        ? "The health check was cancelled."
        : "The evaluation service is unreachable.",
    );
  }
  if (!response.ok) throw await readError(response);
  return (await response.json()) as HealthResponse;
}

export interface EvaluateArgs {
  file: File;
  track: TrackCode;
  signal?: AbortSignal;
}

export async function evaluateResume({
  file,
  track,
  signal,
}: EvaluateArgs): Promise<EvaluationResult> {
  if (USE_MOCK) {
    const { mockEvaluate } = await import("../mocks/mockService");
    return mockEvaluate({ file, track, signal });
  }

  const form = new FormData();
  form.append("resume", file, file.name);
  form.append("track", track);

  // The caller's signal cancels; this one is the ceiling. Combining them keeps a user
  // cancel distinguishable from a timeout.
  const ceiling = new AbortController();
  const timer = window.setTimeout(() => ceiling.abort(), EVALUATE_TIMEOUT_MS);
  signal?.addEventListener("abort", () => ceiling.abort(), { once: true });

  let response: Response;
  try {
    response = await fetch(`${BASE}/api/evaluate`, {
      method: "POST",
      body: form,
      signal: ceiling.signal,
    });
  } catch (error) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    if (ceiling.signal.aborted) throw new TimeoutError();
    throw new NetworkError(
      "The evaluation service is unreachable. Check that the Python API is running.",
    );
  } finally {
    window.clearTimeout(timer);
  }

  if (!response.ok) throw await readError(response);

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new MalformedResponseError(["the response body was not JSON"]);
  }
  return validateEvaluation(payload);
}
