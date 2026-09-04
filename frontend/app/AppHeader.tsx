import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowLeft, Captions, ChevronRight, Settings } from "lucide-react";
import { useT } from "next-i18next/client";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { ThemeToggle } from "./ThemeToggle";

export function AppHeader({
  page = "home",
  jobsControl,
  refreshControl,
}: {
  page?: "home" | "settings";
  jobsControl?: ReactNode;
  refreshControl?: ReactNode;
}) {
  const { t, i18n } = useT("common");
  const settingsPage = page === "settings";
  const localePrefix = i18n.language === "en" ? "" : `/${i18n.language}`;

  return (
    <header className="hero">
      <div className="mark" aria-hidden="true">
        <Captions size={20} strokeWidth={1.75} />
      </div>
      <div className="brandCopy">
        <h1>{settingsPage ? t("header.settingsTitle") : t("appName")}</h1>
        <p className="lede">
          {settingsPage
            ? t("header.settingsDescription")
            : t("header.homeDescription")}
        </p>
      </div>
      <div className="headerActions">
        {settingsPage && <>
          <LanguageSwitcher />
          <ThemeToggle />
        </>}
        {refreshControl}
        {jobsControl}
        <Link className="settingsLink" href={settingsPage ? `${localePrefix}/` : `${localePrefix}/settings/`}>
          {settingsPage
            ? <ArrowLeft size={16} strokeWidth={1.75} />
            : <Settings size={16} strokeWidth={1.75} />}
          <span>{settingsPage ? t("header.media") : t("header.settings")}</span>
          {!settingsPage && <ChevronRight size={14} strokeWidth={1.75} aria-hidden="true" />}
        </Link>
      </div>
    </header>
  );
}
