import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { notFound } from "next/navigation";
import { I18nProvider } from "next-i18next/client";
import {
  generateI18nStaticParams,
  getResources,
  getT,
  initServerI18next,
} from "next-i18next/server";
import i18nConfig, { defaultLocale, isSupportedLocale } from "../../i18n.config";
import "../styles/tokens.scss";
import "../globals.css";

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
    const stored = localStorage.getItem("subtitle-maker-theme");
    const theme = stored === "light" || stored === "dark"
      ? stored
      : (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    document.documentElement.dataset.theme = theme;
  } catch (_) {}
`;

initServerI18next(i18nConfig);

export function generateStaticParams() {
  return generateI18nStaticParams();
}

export const dynamicParams = false;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ lng: string }>;
}): Promise<Metadata> {
  const { lng } = await params;
  if (!isSupportedLocale(lng)) notFound();
  const { t } = await getT("common", { lng });
  return {
    title: t("appName"),
    description: t("meta.description"),
  };
}

export default async function LocalizedRootLayout({
  children,
  params,
}: Readonly<{
  children: React.ReactNode;
  params: Promise<{ lng: string }>;
}>) {
  const { lng } = await params;
  if (!isSupportedLocale(lng)) notFound();

  const { i18n } = await getT(undefined, { lng });
  const languages = lng === defaultLocale ? [lng] : [lng, defaultLocale];
  const resources = getResources(i18n, i18nConfig.ns, languages);

  return (
    <html lang={lng} suppressHydrationWarning className={`${geistSans.variable} ${geistMono.variable}`}>
      <head><script dangerouslySetInnerHTML={{ __html: themeScript }} /></head>
      <body>
        <I18nProvider
          language={lng}
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
