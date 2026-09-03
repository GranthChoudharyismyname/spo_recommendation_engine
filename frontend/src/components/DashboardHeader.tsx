import { TriangleAlert } from "lucide-react";
import type { ThemeChoice } from "../lib/theme";
import { Logo, Wordmark } from "./Logo";
import { Chip, Tooltip } from "./primitives";
import { ThemeToggle } from "./ThemeToggle";

export function DashboardHeader({
  mock,
  theme,
  onThemeChange,
}: {
  mock: boolean;
  theme: ThemeChoice;
  onThemeChange: (c: ThemeChoice) => void;
}) {
  return (
    <header
      className="glass sticky top-0 z-30 flex items-center gap-4 px-4 py-2.5"
      style={{ borderRadius: 0, borderWidth: "0 0 1px", borderColor: "var(--colour-hairline)" }}
    >
      <div className="flex min-w-0 items-center gap-2.5">
        <span className="shrink-0" style={{ color: "var(--colour-ink)" }}>
          <Logo size={34} />
        </span>
        <div className="min-w-0">
          <h1 className="truncate">
            <Wordmark />
          </h1>
        </div>
      </div>

      <div className="ml-auto flex items-center gap-2">
        {mock ? (
          <Tooltip content="Showing the bundled sample. No resume is being scored.">
            <span tabIndex={0}>
              <Chip tone="caution" icon={<TriangleAlert size={12} />}>
                Sample data
              </Chip>
            </span>
          </Tooltip>
        ) : null}
        <ThemeToggle choice={theme} onChange={onThemeChange} />
      </div>
    </header>
  );
}
