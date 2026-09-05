import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { I18nProvider } from "next-i18next/client";
import { getResources, getT, initServerI18next } from "next-i18next/server";
import i18nConfig, { defaultLocale } from "../../i18n.config";
import "../styles/tokens.scss";
import "../globals.css";

initServerI18next(i18nConfig);

const geistSans = Geist({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-geist-sans",
});

const geistMono = Geist_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-geist-mono",
});

const themeScript = `
  try {
    const stored = localStorage.getItem("cue-theme");
    const theme = stored === "light" || stored === "dark"
      ? stored
      : (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    document.documentElement.dataset.theme = theme;
  } catch (_) {}
`;

export const metadata: Metadata = {
  title: "Cue",
  description: "Create and synchronize multilingual subtitles from your video library",
};

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const { i18n } = await getT(undefined, { lng: defaultLocale });
  const resources = getResources(i18n, i18nConfig.ns, [defaultLocale]);

  return (
    <html lang={defaultLocale} suppressHydrationWarning className={`${geistSans.variable} ${geistMono.variable}`}>
      <head><script dangerouslySetInnerHTML={{ __html: themeScript }} /></head>
      <body>
        <I18nProvider
          language={defaultLocale}
          resources={resources}
          supportedLngs={i18nConfig.supportedLngs}
          fallbackLng={i18nConfig.fallbackLng}
          defaultNS={i18nConfig.defaultNS}
        >
          {children}
        </I18nProvider>
      </body>
    </html>
  );
}
