import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowLeft, Captions, ChevronRight, Settings } from "lucide-react";
import { ThemeToggle } from "./ThemeToggle";

export function AppHeader({
  page = "home",
  jobsControl,
}: {
  page?: "home" | "settings";
  jobsControl?: ReactNode;
}) {
  const settingsPage = page === "settings";

  return (
    <header className="hero">
      <div className="mark" aria-hidden="true">
        <Captions size={20} strokeWidth={1.75} />
      </div>
      <div className="brandCopy">
        <h1>{settingsPage ? "Settings" : "Subtitle Maker"}</h1>
        <p className="lede">
          {settingsPage
            ? "Configure subtitle sources, models, and local credentials."
            : "Find, synchronize, and translate subtitles without downloading the full video."}
        </p>
      </div>
      <div className="headerActions">
        <ThemeToggle />
        {jobsControl}
        <Link className="settingsLink" href={settingsPage ? "/" : "/settings/"}>
          {settingsPage
            ? <ArrowLeft size={16} strokeWidth={1.75} />
            : <Settings size={16} strokeWidth={1.75} />}
          <span>{settingsPage ? "Media" : "Settings"}</span>
          {!settingsPage && <ChevronRight size={14} strokeWidth={1.75} aria-hidden="true" />}
        </Link>
      </div>
    </header>
  );
}
