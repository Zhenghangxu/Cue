"use client";

import { Languages } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useT } from "next-i18next/client";
import { defaultLocale, supportedLocales, type AppLocale } from "../i18n.config";

const LANGUAGE_NAMES: Record<AppLocale, string> = {
  en: "English",
  zh: "中文",
};

export function LanguageSwitcher() {
  const pathname = usePathname();
  const router = useRouter();
  const { t, i18n } = useT("common");
  const currentLocale = supportedLocales.includes(i18n.language as AppLocale)
    ? i18n.language as AppLocale
    : defaultLocale;

  function switchLocale(locale: AppLocale) {
    const segments = pathname.split("/").filter(Boolean);
    if (supportedLocales.includes(segments[0] as AppLocale)) segments.shift();
    const suffix = segments.length ? `/${segments.join("/")}/` : "/";
    const href = locale === defaultLocale ? suffix : `/${locale}${suffix}`;
    document.cookie = `i18next=${locale}; path=/; max-age=31536000; samesite=lax`;
    router.push(href);
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
