/**
 * A draggable divider between two workspace columns.
 *
 * Exposed as a real separator with keyboard support, not just a mousedown target: a
 * column width is a genuine preference and dragging is not available to everyone. Arrow
 * keys nudge, Home resets.
 */

import { useCallback, useEffect, useRef, useState } from "react";

const NUDGE = 16;

export function ResizeHandle({
  value,
  min,
  max,
  /** "left" when the handle sits to the right of the column it sizes. */
  edge,
  label,
  onChange,
  onNudge,
  onReset,
}: {
  value: number;
  min: number;
  max: number;
  edge: "left" | "right";
  label: string;
  onChange: (next: number) => void;
  /** Relative move, so repeated keypresses cannot read a stale width. */
  onNudge: (delta: number) => void;
  onReset: () => void;
}) {
  const [dragging, setDragging] = useState(false);
  const origin = useRef({ x: 0, value: 0 });

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: PointerEvent) => {
      const delta = e.clientX - origin.current.x;
      // Dragging right widens a left-hand column and narrows a right-hand one.
      onChange(origin.current.value + (edge === "left" ? delta : -delta));
    };
    const onUp = () => setDragging(false);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    // Without this the PDF and text below the cursor select while dragging.
    const previous = document.body.style.userSelect;
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      document.body.style.userSelect = previous;
      document.body.style.cursor = "";
    };
  }, [dragging, edge, onChange]);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const towardsWider = edge === "left" ? "ArrowRight" : "ArrowLeft";
      const towardsNarrower = edge === "left" ? "ArrowLeft" : "ArrowRight";
      if (e.key === towardsWider) onNudge(NUDGE);
      else if (e.key === towardsNarrower) onNudge(-NUDGE);
      else if (e.key === "Home") return onReset();
      else return;
      e.preventDefault();
    },
    [edge, onNudge, onReset],
  );

  return (
    <div
      role="separator"
      aria-label={label}
      aria-orientation="vertical"
      aria-valuenow={Math.round(value)}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      onPointerDown={(e) => {
        e.preventDefault();
        origin.current = { x: e.clientX, value };
        setDragging(true);
      }}
      onDoubleClick={onReset}
      onKeyDown={onKeyDown}
      title={`${label} — drag, arrow keys, or double-click to reset`}
      className="group relative shrink-0 cursor-col-resize self-stretch rounded-full
        focus-visible:outline-none"
      style={{ width: 5, marginInline: -1 }}
    >
      {/* The visible line is thin; the hit area above is deliberately wider. */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-y-2 left-1/2 w-px -translate-x-1/2
          rounded-full transition-colors group-hover:w-[3px]
          group-focus-visible:w-[3px]"
        style={{
          background: dragging ? "var(--colour-indigo)" : "var(--colour-hairline-strong)",
          transitionDuration: "var(--motion-fast)",
        }}
      />
    </div>
  );
}
