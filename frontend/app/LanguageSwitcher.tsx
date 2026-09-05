"use client";

import { Languages } from "lucide-react";
import { usePathname } from "next/navigation";
import { directoryFromPathname, directoryPathname } from "./directoryRouting";
import { useT } from "next-i18next/client";
import { defaultLocale, supportedLocales, type AppLocale } from "../i18n.config";

const LANGUAGE_NAMES: Record<AppLocale, string> = {
  en: "English",
  zh: "中文",
};

export function LanguageSwitcher() {
  const pathname = usePathname();
  const { t, i18n } = useT("common");
  const currentLocale = supportedLocales.includes(i18n.language as AppLocale)
    ? i18n.language as AppLocale
    : defaultLocale;

  function switchLocale(locale: AppLocale) {
    const settings = /^\/(?:en\/|zh\/)?settings\/?$/.test(pathname);
    const href = settings
      ? `${locale === defaultLocale ? "" : `/${locale}`}/settings/`
      : directoryPathname(directoryFromPathname(pathname), locale);
    document.cookie = `i18next=${locale}; path=/; max-age=31536000; samesite=lax`;
    // Directory pages are served by the static host's fallback, not RSC routes.
    window.location.assign(href);
  }

  return (
    <label className="languageSwitcher">
      <Languages size={16} strokeWidth={1.75} aria-hidden="true" />
      <span className="srOnly">{t("language.label")}</span>
      <select
        aria-label={t("language.label")}
        value={currentLocale}
        onChange={(event) => switchLocale(event.target.value as AppLocale)}
      >
        {supportedLocales.map((locale) => (
          <option key={locale} value={locale}>{LANGUAGE_NAMES[locale]}</option>
        ))}
      </select>
    </label>
  );
}
