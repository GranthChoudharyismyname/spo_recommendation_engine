/**
 * Theme preference.
 *
 * Three states, not two: "system" is the default and follows the OS, while "light" and
 * "dark" are explicit choices that override it. The distinction matters — a viewer who
 * has never touched the control should track their OS when it changes, and one who has
 * chosen should not be overridden by it.
 *
 * The choice is written to the root element as `data-theme`, which is what the token
 * stylesheet keys off, and persisted per browser. Storage can throw outright in a
 * private window or with site data blocked, so every access is guarded and a failure
 * simply means the preference does not persist.
 */

import { useCallback, useEffect, useState } from "react";

export type ThemeChoice = "light" | "dark" | "system";

const STORAGE_KEY = "resumetr.theme";

function read(): ThemeChoice {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "light" || raw === "dark" || raw === "system") return raw;
  } catch {
    /* private window, or site data blocked */
  }
  return "system";
}

/** Applied to <html>; "system" clears the attribute so the media query takes over. */
function apply(choice: ThemeChoice) {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
}

/** Set before React mounts, so the first paint is already the right theme. */
export function initTheme() {
  apply(read());
}

export function useTheme() {
  const [choice, setChoice] = useState<ThemeChoice>(read);

  useEffect(() => {
    apply(choice);
    try {
      localStorage.setItem(STORAGE_KEY, choice);
    } catch {
      /* preference simply will not persist */
    }
  }, [choice]);

  /** What is actually on screen right now, which "system" alone does not tell you. */
  const resolved: "light" | "dark" =
    choice === "system"
      ? window.matchMedia?.("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : choice;

  // Following the OS means re-rendering when it changes, not only at mount.
  const [, force] = useState(0);
  useEffect(() => {
    if (choice !== "system" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => force((n) => n + 1);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [choice]);

  const cycle = useCallback(() => {
    setChoice((c) => (c === "light" ? "dark" : c === "dark" ? "system" : "light"));
  }, []);

  return { choice, resolved, setChoice, cycle };
}
