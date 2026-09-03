/**
 * Light / dark / system, as one control.
 *
 * A three-way segmented control rather than a cycling button: with three states a single
 * toggle gives no way to see which one is active, and "system" is invisible unless it is
 * shown as its own option.
 */

import { Monitor, Moon, Sun } from "lucide-react";
import type { ThemeChoice } from "../lib/theme";
import { Tooltip } from "./primitives";

const OPTIONS: { value: ThemeChoice; label: string; Icon: typeof Sun }[] = [
  { value: "light", label: "Light", Icon: Sun },
  { value: "dark", label: "Dark", Icon: Moon },
  { value: "system", label: "Match system", Icon: Monitor },
];

export function ThemeToggle({
  choice,
  onChange,
}: {
  choice: ThemeChoice;
  onChange: (c: ThemeChoice) => void;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className="flex items-center gap-0.5 rounded-full p-0.5"
      style={{
        background: "var(--colour-glass-sunken)",
        border: "1px solid var(--colour-hairline)",
      }}
    >
      {OPTIONS.map(({ value, label, Icon }) => {
        const active = choice === value;
        return (
          <Tooltip key={value} content={label}>
            <button
              type="button"
              role="radio"
              aria-checked={active}
              aria-label={label}
              onClick={() => onChange(value)}
              className="grid h-6 w-6 place-items-center rounded-full transition-colors"
              style={{
                background: active ? "var(--colour-indigo-soft)" : "transparent",
                color: active ? "var(--colour-indigo)" : "var(--colour-ink-faint)",
              }}
            >
              <Icon size={13} aria-hidden />
            </button>
          </Tooltip>
        );
      })}
    </div>
  );
}
