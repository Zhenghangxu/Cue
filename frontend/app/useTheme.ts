"use client";

import { useCallback, useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

const THEME_EVENT = "cue-theme-change";

function getTheme(): Theme | null {
  if (typeof document === "undefined") return null;
  const current = document.documentElement.dataset.theme;
  return current === "light" || current === "dark" ? current : null;
}

function subscribe(onStoreChange: () => void) {
  window.addEventListener(THEME_EVENT, onStoreChange);
  return () => window.removeEventListener(THEME_EVENT, onStoreChange);
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, getTheme, () => null);

  const setTheme = useCallback((next: Theme) => {
    document.documentElement.dataset.theme = next;
    localStorage.setItem("cue-theme", next);
    window.dispatchEvent(new Event(THEME_EVENT));
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(theme === "dark" ? "light" : "dark");
  }, [setTheme, theme]);

  return { theme, toggleTheme };
}
