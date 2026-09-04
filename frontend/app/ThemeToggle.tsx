"use client";

import { Moon, Sun } from "lucide-react";
import { useT } from "next-i18next/client";
import { useTheme } from "./useTheme";

export function ThemeToggle() {
  const { t } = useT("common");
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";
  const label = isDark ? t("theme.switchToLight") : t("theme.switchToDark");

  return (
    <button
      className="themeToggle"
      type="button"
      onClick={toggleTheme}
      aria-label={label}
      title={label}
    >
      {isDark ? <Sun size={16} strokeWidth={1.75} /> : <Moon size={16} strokeWidth={1.75} />}
    </button>
  );
}
