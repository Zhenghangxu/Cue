"use client";

import { themeColors } from "./theme";
import { useTheme } from "./useTheme";

export function ThemeColor() {
  const { theme } = useTheme();
  // React hoists this into <head> and keeps it in sync across navigation.
  return <meta name="theme-color" content={themeColors[theme ?? "light"]} />;
}
