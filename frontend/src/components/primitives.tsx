import { createContext, useContext } from "react";
import type { CSSProperties, ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import * as RadixTooltip from "@radix-ui/react-tooltip";

/* ------------------------------------------------------------------ folding
 *
 * A panel folds by hiding every child after its header, so a panel opts in with one
 * `foldId` prop and needs no other change. The workspace supplies the state; the panel
 * supplies its identity, and SectionHeader — which is always that first child — draws
 * the control.
 */

interface FoldState {
  folded: Set<string>;
  toggle: (id: string) => void;
}

export const FoldContext = createContext<FoldState | null>(null);
const PanelFoldContext = createContext<string | null>(null);

/* ------------------------------------------------------------------ Panel */

export function Panel({
  children,
  className = "",
  style,
  foldId,
}: {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  /** Opts this panel into folding, and names it in the stored layout. */
  foldId?: string;
}) {
  const fold = useContext(FoldContext);
  const isFolded = !!foldId && !!fold?.folded.has(foldId);

  return (
    <PanelFoldContext.Provider value={foldId ?? null}>
      <section
        className={`glass ${isFolded ? "is-folded" : ""} ${className}`}
        style={style}
      >
        {children}
      </section>
    </PanelFoldContext.Provider>
  );
}

export function SectionHeader({
  title,
  eyebrow,
  meta,
  action,
}: {
  title: string;
  eyebrow?: string;
  meta?: ReactNode;
  action?: ReactNode;
}) {
  const fold = useContext(FoldContext);
  const foldId = useContext(PanelFoldContext);
  const foldable = !!foldId && !!fold;
  const isFolded = foldable && fold.folded.has(foldId);

  const heading = (
    <div className="min-w-0">
      {eyebrow ? <p className="eyebrow mb-1">{eyebrow}</p> : null}
      <h2 className="truncate" style={{ font: "var(--type-title)", color: "var(--colour-ink)" }}>
        {title}
      </h2>
    </div>
  );

  return (
    <header className="flex items-baseline justify-between gap-4">
      {foldable ? (
        <button
          type="button"
          onClick={() => fold.toggle(foldId)}
          aria-expanded={!isFolded}
          className="-m-1 flex min-w-0 flex-1 items-baseline gap-1.5 rounded-[var(--radius-sm)]
            p-1 text-left"
        >
          <ChevronDown
            size={14}
            aria-hidden
            className="mt-0.5 shrink-0 transition-transform"
            style={{
              color: "var(--colour-ink-faint)",
              transform: isFolded ? "rotate(-90deg)" : "none",
              transitionDuration: "var(--motion-fast)",
            }}
          />
          {heading}
        </button>
      ) : (
        heading
      )}
      {meta ? <div className="shrink-0">{meta}</div> : null}
      {action ? <div className="shrink-0">{action}</div> : null}
    </header>
  );
}

/* ------------------------------------------------------------------ Chip */

export function Chip({
  children,
  tone = "neutral",
  icon,
  title,
}: {
  children: ReactNode;
  tone?: "neutral" | "indigo" | "strong" | "caution" | "critical";
  icon?: ReactNode;
  title?: string;
}) {
  const map = {
    neutral: ["var(--colour-ink-muted)", "rgba(23,38,74,0.06)"],
    indigo: ["var(--colour-indigo-deep)", "var(--colour-indigo-soft)"],
    strong: ["var(--colour-strong)", "var(--colour-strong-soft)"],
    caution: ["var(--colour-caution)", "var(--colour-caution-soft)"],
    critical: ["var(--colour-critical)", "var(--colour-critical-soft)"],
  } as const;
  const [fg, bg] = map[tone];
  return (
    <span
      title={title}
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 whitespace-nowrap"
      style={{ font: "var(--type-label)", color: fg, background: bg }}
    >
      {icon}
      {children}
    </span>
  );
}

/* ------------------------------------------------------------------ Button */

export function Button({
  children,
  onClick,
  variant = "primary",
  disabled,
  type = "button",
  icon,
  full,
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "ghost" | "quiet";
  disabled?: boolean;
  type?: "button" | "submit";
  icon?: ReactNode;
  full?: boolean;
  title?: string;
}) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-[var(--radius-md)] px-4 py-2.5 " +
    "transition-[background,box-shadow,color,transform] disabled:cursor-not-allowed";
  const styles: Record<string, CSSProperties> = {
    primary: {
      background: disabled ? "rgba(68,87,201,0.32)" : "var(--colour-indigo)",
      color: "#fff",
      boxShadow: disabled ? "none" : "var(--shadow-panel)",
    },
    ghost: {
      background: "var(--colour-glass-raised)",
      color: "var(--colour-ink-soft)",
      border: "1px solid var(--colour-hairline-strong)",
    },
    quiet: { background: "transparent", color: "var(--colour-ink-muted)" },
  };
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={`${base} ${full ? "w-full" : ""}`}
      style={{
        font: "var(--type-title-sm)",
        transitionDuration: "var(--motion-fast)",
        ...styles[variant],
      }}
    >
      {icon}
      {children}
    </button>
  );
}

export function IconButton({
  label,
  onClick,
  children,
  disabled,
  active,
}: {
  label: string;
  onClick?: () => void;
  children: ReactNode;
  disabled?: boolean;
  active?: boolean;
}) {
  return (
    <Tooltip content={label}>
      <button
        type="button"
        aria-label={label}
        onClick={onClick}
        disabled={disabled}
        className="grid h-8 w-8 place-items-center rounded-[var(--radius-sm)] transition-colors disabled:opacity-35"
        style={{
          color: active ? "var(--colour-indigo-deep)" : "var(--colour-ink-muted)",
          background: active ? "var(--colour-indigo-soft)" : "transparent",
          transitionDuration: "var(--motion-fast)",
        }}
      >
        {children}
      </button>
    </Tooltip>
  );
}

/* ------------------------------------------------------------------ Tooltip */

export function TooltipProvider({ children }: { children: ReactNode }) {
  return (
    <RadixTooltip.Provider delayDuration={260} skipDelayDuration={200}>
      {children}
    </RadixTooltip.Provider>
  );
}

export function Tooltip({
  content,
  children,
  side = "top",
}: {
  content: ReactNode;
  children: ReactNode;
  side?: "top" | "bottom" | "left" | "right";
}) {
  return (
    <RadixTooltip.Root>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          side={side}
          sideOffset={6}
          collisionPadding={12}
          className="z-50 max-w-[19rem] rounded-[var(--radius-sm)] px-2.5 py-2"
          style={{
            font: "var(--type-body-sm)",
            color: "#f4f6fb",
            background: "rgba(16,28,52,0.95)",
            boxShadow: "var(--shadow-raised)",
          }}
        >
          {content}
          <RadixTooltip.Arrow style={{ fill: "rgba(16,28,52,0.95)" }} />
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  );
}

/* ------------------------------------------------------------------ Skeleton */

export function Skeleton({ h = 12, w = "100%" }: { h?: number; w?: number | string }) {
  return <div className="skeleton" style={{ height: h, width: w }} aria-hidden />;
}
