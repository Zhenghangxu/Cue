"use client";

import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { filterAndSortEntries, type EntrySort } from "./fileEntries";

type FileEntry = {
  name: string;
  path: string;
  type: "directory" | "video";
  size?: number | null;
  modified?: string | null;
};

type JobResult = {
  outputPath?: string;
  sourceLanguage?: string;
  release?: string;
  moviehashMatch?: boolean;
  quota?: { remaining?: number | null; resetTimeUtc?: string | null };
  aiUsage?: { promptTokens: number; completionTokens: number; totalTokens: number };
  from?: string;
  to?: string;
};

type JobItem = {
  path: string;
  status: string;
  message: string;
  error?: string | null;
  result?: JobResult | null;
};

type Job = {
  id: string;
  kind?: "subtitles" | "rename";
  status: string;
  message: string;
  items: JobItem[];
  error?: string | null;
  target_language?: string;
  subtitle_mode?: string;
};

type Health = {
  ready: boolean;
  configuration: string;
  binaries: { ffmpeg: boolean; ffsubsync: boolean };
};

type Option = { value: string; label: string };
type SettingsResponse = {
  values: Record<string, string>;
  options: { subtitle_modes: Option[] };
};

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
const TERMINAL = new Set(["completed", "failed"]);

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

function formatSize(bytes?: number | null) {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
}

export default function Home() {
  const renameDialog = useRef<HTMLDialogElement>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [path, setPath] = useState("");
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<EntrySort>({ key: "modified", direction: "desc" });
  const [selected, setSelected] = useState<string[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [initialQuotaRemaining, setInitialQuotaRemaining] = useState<number | null>(null);
  const [actionMode, setActionMode] = useState<"subtitles" | "rename">("subtitles");
  const [subtitleMode, setSubtitleMode] = useState("bilingual");
  const [subtitleModes, setSubtitleModes] = useState<Option[]>([]);
  const [loading, setLoading] = useState(true);
  const [renaming, setRenaming] = useState(false);
  const [renameTitle, setRenameTitle] = useState("");
  const [renameError, setRenameError] = useState("");
  const [error, setError] = useState("");

  const loadDirectory = useCallback(async (nextPath: string) => {
    setLoading(true);
    setError("");
    setSelected([]);
    setQuery("");
    try {
      const data = await api<{ path: string; entries: FileEntry[] }>(
        `/api/files?path=${encodeURIComponent(nextPath)}`,
      );
      setPath(data.path);
      setEntries(data.entries);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load this directory");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    api<Health>("/api/health")
      .then((value) => {
        setHealth(value);
        if (value.ready) {
          void loadDirectory("");
          void api<{ remaining: number }>("/api/quota")
            .then(({ remaining }) => setInitialQuotaRemaining(remaining))
            .catch(() => setInitialQuotaRemaining(null));
        } else setLoading(false);
      })
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : "Backend is unavailable");
        setLoading(false);
      });

    api<SettingsResponse>("/api/settings")
      .then(({ values, options }) => {
        setSubtitleModes(options.subtitle_modes);
        if (options.subtitle_modes.some(({ value }) => value === values.default_subtitle_mode)) {
          setSubtitleMode(values.default_subtitle_mode);
        }
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Could not load subtitle settings"));

    const remembered = (sessionStorage.getItem("subtitle-maker-jobs")
      ?? sessionStorage.getItem("subtitle-maker-job")
      ?? "").split(",").filter(Boolean);
    if (remembered.length) Promise.all(remembered.map((id) => api<Job>(`/api/jobs/${id}`).catch(() => null)))
      .then((values) => setJobs(values.filter((value): value is Job => Boolean(value))));
  }, [loadDirectory]);

  useEffect(() => {
    const active = jobs.filter((job) => !TERMINAL.has(job.status));
    if (!active.length) return;
    const timer = window.setTimeout(() => {
      Promise.all(active.map((job) => api<Job>(`/api/jobs/${job.id}`)))
        .then((updated) => {
          setJobs((current) => current.map((job) => updated.find(({ id }) => id === job.id) ?? job));
          if (updated.some((job) => job.kind === "rename" && TERMINAL.has(job.status))) {
            void loadDirectory(path);
          }
        })
        .catch((reason) => setError(String(reason)));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [jobs, loadDirectory, path]);

  const crumbs = useMemo(() => {
    const parts = path ? path.split("/") : [];
    return [
      { name: "Media", path: "" },
      ...parts.map((name, index) => ({ name, path: parts.slice(0, index + 1).join("/") })),
    ];
  }, [path]);

  const visibleEntries = useMemo(
    () => filterAndSortEntries(entries, query, sort),
    [entries, query, sort],
  );
  const selectedPaths = entries
    .filter((entry) => entry.type === "video" && selected.includes(entry.path))
    .map((entry) => entry.path);

  function changeSort(key: EntrySort["key"]) {
    setSort((current) => current.key === key
      ? { key, direction: current.direction === "asc" ? "desc" : "asc" }
      : { key, direction: key === "name" ? "asc" : "desc" });
  }

  function queueJob(job: Job) {
    setJobs((current) => {
      const next = [...current, job];
      sessionStorage.setItem("subtitle-maker-jobs", next.map(({ id }) => id).join(","));
      sessionStorage.removeItem("subtitle-maker-job");
      return next;
    });
  }

  async function start() {
    if (!selectedPaths.length) return;
    setError("");
    try {
      const value = await api<{ jobId: string }>("/api/jobs", {
        method: "POST",
        body: JSON.stringify({ paths: selectedPaths, mode: subtitleMode }),
      });
      const queued = {
        id: value.jobId,
        status: "queued",
        message: "Waiting to start",
        subtitle_mode: subtitleMode,
        items: selectedPaths.map((path) => ({ path, status: "queued", message: "Waiting to start" })),
      };
      queueJob(queued);
      setSelected([]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start the job");
    }
  }

  async function rename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedPaths.length) return;
    setRenaming(true);
    setRenameError("");
    try {
      const value = await api<{ jobId: string }>("/api/rename", {
        method: "POST",
        body: JSON.stringify({ paths: selectedPaths, title: renameTitle }),
      });
      renameDialog.current?.close();
      queueJob({
        id: value.jobId,
        kind: "rename",
        status: "queued",
        message: "Waiting to start",
        items: selectedPaths.map((path) => ({ path, status: "queued", message: "Waiting to start" })),
      });
      setSelected([]);
    } catch (reason) {
      setRenameError(reason instanceof Error ? reason.message : "Could not rename the selected videos");
    } finally {
      setRenaming(false);
    }
  }

  const items = jobs.flatMap((job) => job.items);
  const activeItems = jobs.filter((job) => !TERMINAL.has(job.status)).flatMap((job) => job.items);
  const pendingItems = activeItems.filter((item) => !TERMINAL.has(item.status));
  const busy = pendingItems.length > 0;
  const completed = items.filter((item) => item.status === "completed").length;
  const failed = items.filter((item) => item.status === "failed").length;
  const totalTokens = items.reduce((total, item) => total + (item.result?.aiUsage?.totalTokens ?? 0), 0);
  const quotaRemaining = items.reduce<number | null>(
    (remaining, item) => item.result?.quota?.remaining ?? remaining,
    initialQuotaRemaining,
  );
  const actionModeLabel = actionMode === "rename"
    ? "AI-powered VidHub naming"
    : subtitleModes.find(({ value }) => value === subtitleMode)?.label ?? "English & target language";

  return (
    <main>
      <header className="hero">
        <div className="mark" aria-hidden="true">字</div>
        <div>
          <p className="eyebrow">LOCAL WEBDAV TOOL</p>
          <h1>Subtitle Maker</h1>
          <p className="lede">Find, synchronize, and translate subtitles without downloading the full video.</p>
        </div>
        <Link className="settingsLink" href="/settings/">Settings →</Link>
      </header>

      {health && !health.ready && (
        <section className="notice" role="alert">
          <strong>Backend setup is incomplete.</strong>
          <span>{health.configuration}</span>
          {!health.binaries.ffmpeg && <span>FFmpeg is missing.</span>}
          {!health.binaries.ffsubsync && <span>Run <code>uv sync</code> to install ffsubsync.</span>}
        </section>
      )}

      {items.length > 0 && (
        <aside className="queue" aria-live="polite" aria-label="Job queue">
          <div className="queueHeader">
            <div className="queueTitle">
              {busy && <span className="spinner" aria-hidden="true" />}
              <div><p className="eyebrow">QUEUE</p><strong>{busy ? `${pendingItems.length} active` : "All finished"}</strong></div>
            </div>
            <span>{completed} done · {failed} failed</span>
          </div>
          <div className="queueItems">
            {items.map((item, index) => (
              <div className="queueItem" key={`${item.path}-${index}`}>
                <div>
                  <strong title={item.path}>{item.path.split("/").at(-1)}</strong>
                  <small className={item.error ? "queueError" : ""}>{item.error ?? item.message}</small>
                </div>
                <span className={`stage ${item.status}`}>{item.status.replaceAll("_", " ")}</span>
              </div>
            ))}
          </div>
        </aside>
      )}

      <section className="workspace" aria-label="WebDAV video browser">
        <nav className="breadcrumbs" aria-label="Directory path">
          {crumbs.map((crumb, index) => (
            <span key={crumb.path || "root"}>
              {index > 0 && <b aria-hidden="true">/</b>}
              <button title={crumb.name} onClick={() => void loadDirectory(crumb.path)} disabled={loading}>
                {crumb.name}
              </button>
            </span>
          ))}
        </nav>

        <div className="tableTools">
          <input
            type="search"
            aria-label="Search this folder"
            placeholder="Search this folder"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>

        <div className="table" aria-label="Videos">
          <div className="tableHead">
            <button
              type="button"
              aria-label={`Sort by name${sort.key === "name" ? `, currently ${sort.direction === "asc" ? "ascending" : "descending"}` : ""}`}
              onClick={() => changeSort("name")}
            >
              Name <span aria-hidden="true">{sort.key === "name" ? (sort.direction === "asc" ? "↑" : "↓") : ""}</span>
            </button>
            <span>Size</span>
            <button
              type="button"
              aria-label={`Sort by date${sort.key === "modified" ? `, currently ${sort.direction === "asc" ? "ascending" : "descending"}` : ""}`}
              onClick={() => changeSort("modified")}
            >
              Date <span aria-hidden="true">{sort.key === "modified" ? (sort.direction === "asc" ? "↑" : "↓") : ""}</span>
            </button>
          </div>
          {loading && <div className="empty">Loading this directory…</div>}
          {!loading && entries.length === 0 && <div className="empty">No supported videos or folders here.</div>}
          {!loading && entries.length > 0 && visibleEntries.length === 0 && <div className="empty">No matches in this folder.</div>}
          {!loading && visibleEntries.map((entry) => entry.type === "directory" ? (
            <button className="row folder" key={entry.path} onClick={() => void loadDirectory(entry.path)}>
              <span className="name"><i aria-hidden="true">↳</i>{entry.name}</span><span>Folder</span><span>{entry.modified ? new Date(entry.modified).toLocaleDateString() : "—"}</span>
            </button>
          ) : (
            <label className={`row ${selected.includes(entry.path) ? "selected" : ""}`} key={entry.path}>
              <span className="name">
                <input
                  type="checkbox"
                  value={entry.path}
                  checked={selected.includes(entry.path)}
                  onChange={(event) => setSelected((current) => event.target.checked
                    ? [...current, entry.path]
                    : current.filter((path) => path !== entry.path))}
                  disabled={pendingItems.some((item) => item.path === entry.path)}
                />
                {entry.name}
              </span>
              <span>{formatSize(entry.size)}</span>
              <span>{entry.modified ? new Date(entry.modified).toLocaleDateString() : "—"}</span>
            </label>
          ))}
        </div>

        <div className="actions">
          <div>
            <span className="label">Usage</span>
            <strong><span className="usageNumber">{totalTokens.toLocaleString()}</span> AI tokens · <span className="usageNumber">{quotaRemaining ?? "—"}</span> subtitles remain</strong>
          </div>
          <div className="createSplit">
            <button
              className="start"
              onClick={() => {
                if (actionMode === "rename") {
                  setRenameTitle("");
                  setRenameError("");
                  renameDialog.current?.showModal();
                } else void start();
              }}
              disabled={!selected.length || !health?.ready || renaming || (actionMode === "subtitles" && !subtitleModes.length)}
            >
              <span>{actionMode === "rename"
                ? `Rename files (${selected.length})`
                : busy ? `Add to queue (${selected.length})` : `Create subtitles (${selected.length})`}</span>
              <small>{actionModeLabel}</small>
            </button>
            {subtitleModes.length > 0 && <details className="modeMenu">
              <summary aria-label="More actions" title="More actions">⌄</summary>
              <div className="modeOptions">
                {subtitleModes.map((option) => (
                  <button
                    type="button"
                    key={option.value}
                    aria-current={actionMode === "subtitles" && option.value === subtitleMode ? "true" : undefined}
                    onClick={(event) => {
                      setActionMode("subtitles");
                      setSubtitleMode(option.value);
                      event.currentTarget.closest("details")?.removeAttribute("open");
                    }}
                  >
                    <span aria-hidden="true">{actionMode === "subtitles" && option.value === subtitleMode ? "✓" : ""}</span>{option.label}
                  </button>
                ))}
                <button
                  type="button"
                  aria-current={actionMode === "rename" ? "true" : undefined}
                  onClick={(event) => {
                    setActionMode("rename");
                    event.currentTarget.closest("details")?.removeAttribute("open");
                  }}
                >
                  <span aria-hidden="true">{actionMode === "rename" ? "✓" : ""}</span>Smart rename
                </button>
              </div>
            </details>}
          </div>
        </div>
      </section>

      <dialog
        className="renameDialog"
        ref={renameDialog}
        aria-labelledby="rename-title"
        onCancel={(event) => {
          if (renaming) event.preventDefault();
        }}
        onClick={(event) => {
          if (event.target === event.currentTarget && !renaming) event.currentTarget.close();
        }}
      >
        <form onSubmit={rename}>
          <div className="dialogHeader">
            <div>
              <p className="eyebrow">SMART RENAME</p>
              <h2 id="rename-title">Name {selectedPaths.length} selected video{selectedPaths.length === 1 ? "" : "s"}</h2>
            </div>
            <button type="button" aria-label="Close smart rename" onClick={() => renameDialog.current?.close()} disabled={renaming}>×</button>
          </div>
          <label htmlFor="english-title">English title</label>
          <input
            id="english-title"
            value={renameTitle}
            onChange={(event) => setRenameTitle(event.target.value)}
            placeholder="e.g. Game of Thrones"
            maxLength={200}
            autoFocus
            required
            disabled={renaming}
          />
          <p>The AI will keep episode, year, quality, and extension details when they are present.</p>
          {renameError && <p className="dialogError" role="alert">{renameError}</p>}
          <div className="dialogActions">
            <button type="button" onClick={() => renameDialog.current?.close()} disabled={renaming}>Cancel</button>
            <button className="start" type="submit" disabled={renaming || !renameTitle.trim()}>
              {renaming ? "Renaming…" : "Rename files"}<span aria-hidden="true">→</span>
            </button>
          </div>
        </form>
      </dialog>

      {error && <p className="error" role="alert">{error}</p>}
      <footer>Only files inside the configured WebDAV scan path are visible to this app.</footer>
    </main>
  );
}
