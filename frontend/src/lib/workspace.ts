/**
 * Workspace layout the viewer controls: column widths and folded panels.
 *
 * Both are per-viewer conveniences rather than analysis state, so both live in
 * localStorage and both degrade to the default silently. Storage can throw outright in
 * a private window, so every access is guarded — a failure means the layout resets next
 * visit, which is not worth surfacing.
 */

import { useCallback, useEffect, useState } from "react";

/* ------------------------------------------------------------------ folding */

const FOLD_KEY = "resumetr.folded";

function readFolded(): Set<string> {
  try {
    const raw = localStorage.getItem(FOLD_KEY);
    if (raw) return new Set(JSON.parse(raw) as string[]);
  } catch {
    /* no stored layout */
  }
  return new Set();
}

export function useFolding() {
  const [folded, setFolded] = useState<Set<string>>(readFolded);

  const toggle = useCallback((id: string) => {
    setFolded((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      try {
        localStorage.setItem(FOLD_KEY, JSON.stringify([...next]));
      } catch {
        /* preference will not persist */
      }
      return next;
    });
  }, []);

  return { folded, toggle };
}

/* ---------------------------------------------------------------- resizing */

const WIDTH_KEY = "resumetr.columns";

export interface ColumnWidths {
  rail: number;
  viewer: number;
}

/** Bounds keep either column from being dragged to nothing, or crushing the middle. */
export const RAIL_BOUNDS = { min: 240, max: 460, initial: 296 };
export const VIEWER_BOUNDS = { min: 320, max: 900, initial: 520 };

function readWidths(): ColumnWidths {
  try {
    const raw = localStorage.getItem(WIDTH_KEY);
    if (raw) {
      const p = JSON.parse(raw) as Partial<ColumnWidths>;
      if (typeof p.rail === "number" && typeof p.viewer === "number") {
        return { rail: clamp(p.rail, RAIL_BOUNDS), viewer: clamp(p.viewer, VIEWER_BOUNDS) };
      }
    }
  } catch {
    /* no stored layout */
  }
  return { rail: RAIL_BOUNDS.initial, viewer: VIEWER_BOUNDS.initial };
}

function clamp(v: number, b: { min: number; max: number }) {
  return Math.max(b.min, Math.min(b.max, v));
}

export function useColumnWidths() {
  const [widths, setWidths] = useState<ColumnWidths>(readWidths);

  /**
   * Persist from an effect, not from the caller.
   *
   * Writing right after a setState reads the pre-update value, because React has not
   * flushed yet — the stored layout would lag one interaction behind. Watching the
   * committed state instead means whatever is on screen is what gets saved. The delay
   * keeps a drag from writing on every pointermove.
   */
  useEffect(() => {
    const t = setTimeout(() => {
      try {
        localStorage.setItem(WIDTH_KEY, JSON.stringify(widths));
      } catch {
        /* preference will not persist */
      }
    }, 250);
    return () => clearTimeout(t);
  }, [widths]);

  /** Absolute width, used while dragging. */
  const set = useCallback((key: keyof ColumnWidths, value: number) => {
    const bounds = key === "rail" ? RAIL_BOUNDS : VIEWER_BOUNDS;
    setWidths((prev) => ({ ...prev, [key]: clamp(value, bounds) }));
  }, []);

  /**
   * Relative move, used by the keyboard.
   *
   * Keypresses auto-repeat faster than React re-renders, so a caller computing
   * `value + step` from its props would read the same stale width for every repeat and
   * the column would move once. Applying the delta inside the updater always sees the
   * current width.
   */
  const nudge = useCallback((key: keyof ColumnWidths, delta: number) => {
    const bounds = key === "rail" ? RAIL_BOUNDS : VIEWER_BOUNDS;
    setWidths((prev) => ({ ...prev, [key]: clamp(prev[key] + delta, bounds) }));
  }, []);

  const reset = useCallback(() => {
    setWidths({ rail: RAIL_BOUNDS.initial, viewer: VIEWER_BOUNDS.initial });
  }, []);

  return { widths, set, nudge, reset };
}
