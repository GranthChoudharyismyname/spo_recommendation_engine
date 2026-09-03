/**
 * The ResuMetr mark.
 *
 * A gauge, not a letterform: the sweep is the reading, the three descending strokes are
 * resume lines, and the filled tick sits at the arc terminus rather than pinned at
 * maximum. Inlined rather than loaded as an <img> so the resume lines can inherit
 * `currentColor` and the mark inverts on a dark ground without a second file.
 *
 * Source of truth: brand/resumetr-mark.svg
 */

export function Logo({ size = 32, className = "" }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      role="img"
      aria-label="ResuMetr"
      className={className}
    >
      <defs>
        <linearGradient id="rm-sweep" x1="10" y1="54" x2="54" y2="12" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="var(--colour-indigo)" />
          <stop offset="1" stopColor="var(--colour-violet)" />
        </linearGradient>
      </defs>
      <path
        d="M 15.6 50.9 A 23 23 0 1 1 48.4 50.9"
        stroke="url(#rm-sweep)"
        strokeWidth={6}
        strokeLinecap="round"
      />
      <g stroke="currentColor" strokeWidth={4} strokeLinecap="round">
        <line x1="24" y1="26" x2="42" y2="26" />
        <line x1="24" y1="36" x2="37" y2="36" />
        <line x1="24" y1="46" x2="31" y2="46" />
      </g>
      <circle cx="48.4" cy="50.9" r="4.8" fill="var(--colour-violet)" />
    </svg>
  );
}

export function Wordmark() {
  return (
    <span style={{ font: "var(--type-title)", color: "var(--colour-ink)" }}>
      Resu<span style={{ color: "var(--colour-indigo)" }}>Metr</span>
    </span>
  );
}
