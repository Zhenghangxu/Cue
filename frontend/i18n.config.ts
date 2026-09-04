import { defineConfig } from "next-i18next";

export const defaultLocale = "en";
export const supportedLocales = [defaultLocale, "zh"] as const;
export type AppLocale = (typeof supportedLocales)[number];

export function isSupportedLocale(locale: string): locale is AppLocale {
  return supportedLocales.includes(locale as AppLocale);
}

const i18nConfig = defineConfig({
  supportedLngs: [...supportedLocales],
  fallbackLng: defaultLocale,
  defaultNS: "common",
  ns: ["common"],
  localeInPath: true,
  resourceLoader: (language, namespace) =>
    import(`./app/i18n/locales/${language}/${namespace}.json`),
});

export default i18nConfig;
