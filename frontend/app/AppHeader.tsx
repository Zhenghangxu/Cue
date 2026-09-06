import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowLeft, ChevronRight, Settings } from "lucide-react";
import { useT } from "next-i18next/client";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { ThemeToggle } from "./ThemeToggle";

export function AppHeader({
  page = "home",
  jobsControl,
  refreshControl,
  mediaDisabled = false,
}: {
  page?: "home" | "settings";
  jobsControl?: ReactNode;
  refreshControl?: ReactNode;
  mediaDisabled?: boolean;
}) {
  const { t, i18n } = useT("common");
  const settingsPage = page === "settings";
  const localePrefix = i18n.language === "en" ? "" : `/${i18n.language}`;

  return (
    <header className={`hero ${settingsPage ? "settingsHeader" : "homeHeader"}`}>
      <div className="mark" aria-hidden="true">
        <span className="brandLogo" />
      </div>
      <div className="brandCopy">
        <h1>{settingsPage ? t("header.settingsTitle") : t("appName")}</h1>
        {settingsPage && <p className="lede">{t("header.settingsDescription")}</p>}
      </div>
      <div className="headerActions">
        <LanguageSwitcher />
        <ThemeToggle />
        {refreshControl}
        {jobsControl}
        {settingsPage && mediaDisabled ? <button className="settingsLink" type="button" disabled title={t("setup.finishFirst")}>
          <ArrowLeft size={16} strokeWidth={1.75} /><span>{t("header.media")}</span>
        </button> : <Link className="settingsLink" href={settingsPage ? `${localePrefix}/` : `${localePrefix}/settings/`}>
          {settingsPage
            ? <ArrowLeft size={16} strokeWidth={1.75} />
            : <Settings size={16} strokeWidth={1.75} />}
          <span>{settingsPage ? t("header.media") : t("header.settings")}</span>
          {!settingsPage && <ChevronRight size={14} strokeWidth={1.75} aria-hidden="true" />}
        </Link>}
      </div>
    </header>
  );
}
