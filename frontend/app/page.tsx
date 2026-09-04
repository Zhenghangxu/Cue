"use client";

import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Check,
  ChevronDown,
  ChevronRight,
  Folder,
  ListTodo,
  LoaderCircle,
  PanelRightClose,
  PanelRightOpen,
  RefreshCw,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { AppHeader } from "./AppHeader";
import {
  fetchEmbeddedSubtitleStream,
  shouldShowLanguageDash,
  type EmbeddedSubtitleCellState,
} from "./embeddedSubtitles";
import { filterAndSortEntries, type EntrySort } from "./fileEntries";
import { getSubtitleLanguage } from "./subtitleLanguages";
import { formatSubtitleModeLabel } from "./subtitleOptions";

type SidecarSubtitle = {
  name: string;
  path: string;
  language?: string | null;
};

type FileEntry = {
  name: string;
  path: string;
  type: "directory" | "video";
  size?: number | null;
  modified?: string | null;
  subtitles?: SidecarSubtitle[];
};

type JobResult = {
  outputPath?: string;
  existing?: boolean;
  reusedSourceSidecar?: boolean;
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
  started_at?: number | null;
  finished_at?: number | null;
  error?: string | null;
  result?: JobResult | null;
};

type Job = {
  id: string;
  kind?: "subtitles" | "rename";
  status: string;
  message: string;
  items: JobItem[];
  created_at: number;
  finished_at?: number | null;
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
  options: { target_languages: Option[]; subtitle_modes: Option[] };
};
type DirectoryLoadOptions = { refresh?: boolean; resetView?: boolean };
type MetadataLoad = { generation: number; path: string; refresh: boolean; videoPaths: string[] };

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
const TERMINAL = new Set(["completed", "failed"]);
const FILE_LIST_SKELETON_ROWS = 10;
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

function formatElapsedTime(startedAt?: number | null, finishedAt?: number | null) {
  if (startedAt == null) return "0:00";
  const elapsed = Math.max(0, Math.floor((finishedAt ?? Date.now() / 1000) - startedAt));
  const hours = Math.floor(elapsed / 3600);
  const minutes = Math.floor((elapsed % 3600) / 60);
  const seconds = elapsed % 60;

  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export default function Home() {
  const renameDialog = useRef<HTMLDialogElement>(null);
  const jobsDock = useRef<HTMLDivElement>(null);
  const metadataAbort = useRef<AbortController>(null);
  const metadataGeneration = useRef(0);
  const [health, setHealth] = useState<Health | null>(null);
  const [path, setPath] = useState("");
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [embeddedMetadata, setEmbeddedMetadata] = useState<Record<string, EmbeddedSubtitleCellState>>({});
  const [metadataLoad, setMetadataLoad] = useState<MetadataLoad | null>(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<EntrySort>({ key: "modified", direction: "desc" });
  const [languageColumnCollapsed, setLanguageColumnCollapsed] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [queueMinimized, setQueueMinimized] = useState(true);
  const [initialQuotaRemaining, setInitialQuotaRemaining] = useState<number | null>(null);
  const [actionMode, setActionMode] = useState<"subtitles" | "rename">("subtitles");
  const [subtitleMode, setSubtitleMode] = useState("bilingual");
  const [subtitleModes, setSubtitleModes] = useState<Option[]>([]);
  const [targetLanguageName, setTargetLanguageName] = useState("");
  const [sourceType, setSourceType] = useState<"webdav" | "local">("webdav");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [renameTitle, setRenameTitle] = useState("");
  const [renameError, setRenameError] = useState("");
  const [error, setError] = useState("");
  const loadDirectory = useCallback(async (
    nextPath: string,
    { refresh = false, resetView = true }: DirectoryLoadOptions = {},
  ) => {
    const generation = ++metadataGeneration.current;
    metadataAbort.current?.abort();
    setMetadataLoad(null);
    if (refresh) setRefreshing(true);
    else setLoading(true);
    setError("");
    if (resetView) {
      setSelected([]);
      setQuery("");
    }
    try {
      const data = await api<{ path: string; entries: FileEntry[] }>(
        `/api/files?path=${encodeURIComponent(nextPath)}${refresh ? "&refresh=true" : ""}`,
      );
      if (metadataGeneration.current !== generation) return;
      const videoPaths = data.entries
        .filter((entry) => entry.type === "video")
        .map((entry) => entry.path);
      setPath(data.path);
      setEntries(data.entries);
      setEmbeddedMetadata(Object.fromEntries(videoPaths.map((videoPath) => [videoPath, { status: "loading" }])));
      setMetadataLoad({ generation, path: data.path, refresh, videoPaths });
    } catch (reason) {
      if (metadataGeneration.current !== generation) return;
      setError(reason instanceof Error ? reason.message : "Could not load this directory");
    } finally {
      if (metadataGeneration.current === generation) {
        if (refresh) setRefreshing(false);
        else setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (!metadataLoad) return;
    const controller = new AbortController();
    const videoPaths = new Set(metadataLoad.videoPaths);
    metadataAbort.current = controller;

    const finishPending = () => {
      if (metadataGeneration.current !== metadataLoad.generation) return;
      setEmbeddedMetadata((current) => Object.fromEntries(Object.entries(current).map(([videoPath, value]) => [
        videoPath,
        value.status === "loading"
          ? { path: videoPath, status: "unavailable", languages: [] }
          : value,
      ])));
    };

    const timer = window.setTimeout(() => {
      const query = new URLSearchParams({ path: metadataLoad.path });
      if (metadataLoad.refresh) query.set("refresh", "true");
      void fetchEmbeddedSubtitleStream(
        `${API}/api/files/embedded-subtitles?${query}`,
        controller.signal,
        (metadata) => {
          if (
            metadataGeneration.current !== metadataLoad.generation
            || !videoPaths.has(metadata.path)
          ) return;
          setEmbeddedMetadata((current) => ({ ...current, [metadata.path]: metadata }));
        },
      ).then(finishPending).catch((reason: unknown) => {
        if ((reason as Error)?.name !== "AbortError") finishPending();
      });
    }, 0);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
      if (metadataAbort.current === controller) metadataAbort.current = null;
    };
  }, [metadataLoad]);

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
        setTargetLanguageName(
          options.target_languages.find(({ value }) => value === values.target_language)?.label
            ?? values.target_language,
        );
        setSourceType(values.source_type === "local" ? "local" : "webdav");
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
            void loadDirectory(path, { refresh: true, resetView: false });
          }
        })
        .catch((reason) => setError(String(reason)));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [jobs, loadDirectory, path]);

  useEffect(() => {
    if (queueMinimized) return;

    function dismissQueue(event: PointerEvent) {
      if (!jobsDock.current?.contains(event.target as Node)) setQueueMinimized(true);
    }

    document.addEventListener("pointerdown", dismissQueue);
    return () => document.removeEventListener("pointerdown", dismissQueue);
  }, [queueMinimized]);

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

  function clearFinishedJobs() {
    setJobs((current) => {
      const next = current.filter((job) => !TERMINAL.has(job.status));
      sessionStorage.setItem("subtitle-maker-jobs", next.map(({ id }) => id).join(","));
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
        created_at: Date.now() / 1000,
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
        created_at: Date.now() / 1000,
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
  const [, setElapsedTimerTick] = useState(0);
  const completed = items.filter((item) => item.status === "completed").length;
  const failed = items.filter((item) => item.status === "failed").length;
  const totalTokens = items.reduce((total, item) => total + (item.result?.aiUsage?.totalTokens ?? 0), 0);
  const quotaRemaining = items.reduce<number | null>(
    (remaining, item) => item.result?.quota?.remaining ?? remaining,
    initialQuotaRemaining,
  );
  const selectedSubtitleMode = subtitleModes.find(({ value }) => value === subtitleMode);
  const actionModeLabel = actionMode === "rename"
    ? "AI-powered video naming"
    : selectedSubtitleMode
      ? formatSubtitleModeLabel(selectedSubtitleMode.label, targetLanguageName)
      : "Loading subtitle options…";

  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => setElapsedTimerTick((tick) => tick + 1), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  return (
    <main>
      <AppHeader jobsControl={(
        <div className="jobsDock" ref={jobsDock}>
          <button
            className={`jobsButton${busy ? " busy" : ""}`}
            type="button"
            onClick={() => setQueueMinimized((current) => !current)}
            aria-label={busy
              ? `Jobs, ${jobs.length} total, ${pendingItems.length} active`
              : `Jobs, ${jobs.length} total`}
            aria-expanded={!queueMinimized}
            aria-controls="job-queue"
          >
            {busy
              ? <LoaderCircle className="spinner" size={16} strokeWidth={1.75} aria-hidden="true" />
              : <ListTodo size={16} strokeWidth={1.75} aria-hidden="true" />}
            <span>Jobs</span>
            <span className="jobsBadge" aria-hidden="true">{pendingItems.length}</span>
          </button>

          {!queueMinimized && (
            <aside id="job-queue" className="queue" aria-live="polite" aria-label="Job queue">
              <div className="queueHeader">
                <div className="queueSummary">
                  {busy && <LoaderCircle className="spinner" size={16} strokeWidth={1.75} aria-hidden="true" />}
                  <span><strong>{completed}</strong> done · <strong>{failed}</strong> failed</span>
                  <b>{busy ? `${pendingItems.length} active` : items.length ? "All finished" : "No jobs"}</b>
                </div>
                <div className="queueControls">
                  <button
                    className="queueIconButton"
                    type="button"
                    onClick={clearFinishedJobs}
                    disabled={!jobs.some((job) => TERMINAL.has(job.status))}
                    aria-label="Clear finished jobs from this list only"
                    aria-describedby="clear-jobs-tooltip"
                  >
                    <Trash2 size={14} strokeWidth={1.75} aria-hidden="true" />
                    <span className="queueTooltip" id="clear-jobs-tooltip" role="tooltip">
                      Only clears UI
                    </span>
                  </button>
                </div>
              </div>
              <div className="queueItems">
                {items.length === 0 && <div className="queueEmpty">No jobs have been created yet.</div>}
                {jobs.flatMap((job) => job.items.map((item, index) => {
                  const elapsedTime = formatElapsedTime(item.started_at, item.finished_at);
                  return (
                    <div className="queueItem" key={`${job.id}-${item.path}-${index}`}>
                      <div>
                        <strong title={item.path}>{item.path.split("/").at(-1)}</strong>
                        <small className={item.error ? "queueError" : ""}>{item.error ?? item.message}</small>
                      </div>
                      <span className="queueTimer" role="timer" aria-label={`Elapsed time ${elapsedTime}`}>
                        {elapsedTime}
                      </span>
                      <span className={`stage ${item.status}`}>{item.status.replaceAll("_", " ")}</span>
                    </div>
                  );
                }))}
              </div>
            </aside>
          )}
        </div>
      )} refreshControl={(
        <button
          className="refreshButton"
          type="button"
          onClick={() => void loadDirectory(path, { refresh: true, resetView: false })}
          disabled={loading || refreshing || !health?.ready}
          aria-label={refreshing ? "Refreshing media" : "Refresh media"}
          title={refreshing ? "Refreshing media" : "Refresh media"}
        >
          <RefreshCw className={refreshing ? "spinner" : undefined} size={16} strokeWidth={1.75} aria-hidden="true" />
        </button>
      )} />

      {health && !health.ready && (
        <section className="notice" role="alert">
          <strong>Backend setup is incomplete.</strong>
          <span>{health.configuration}</span>
          {!health.binaries.ffmpeg && <span>FFmpeg is missing.</span>}
          {!health.binaries.ffsubsync && <span>Run <code>uv sync</code> to install ffsubsync.</span>}
        </section>
      )}

      <section className="workspace" aria-label={`${sourceType === "local" ? "Local" : "WebDAV"} video browser`}>
        <nav className="breadcrumbs" aria-label="Directory path">
          {crumbs.map((crumb, index) => (
            <span className={index === crumbs.length - 1 ? "current" : undefined} key={crumb.path || "root"}>
              {index > 0 && <ChevronRight size={14} strokeWidth={1.75} aria-hidden="true" />}
              <button
                type="button"
                title={crumb.name}
                onClick={() => void loadDirectory(crumb.path)}
                disabled={loading}
                aria-current={index === crumbs.length - 1 ? "page" : undefined}
              >
                {crumb.name}
              </button>
            </span>
          ))}
        </nav>

        <div className="tableTools">
          <label className="searchField">
            <Search size={16} strokeWidth={1.75} aria-hidden="true" />
            <input
              type="search"
              aria-label="Search this folder"
              placeholder="Search this folder"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
        </div>

        <div className={`table${languageColumnCollapsed ? " languageCollapsed" : ""}`} aria-label="Videos">
          <div className="tableHead">
            <button
              type="button"
              aria-label={`Sort by name${sort.key === "name" ? `, currently ${sort.direction === "asc" ? "ascending" : "descending"}` : ""}`}
              onClick={() => changeSort("name")}
            >
              Name
              {sort.key === "name" && (sort.direction === "asc"
                ? <ArrowUp size={12} strokeWidth={1.75} aria-hidden="true" />
                : <ArrowDown size={12} strokeWidth={1.75} aria-hidden="true" />)}
            </button>
            <span>Size</span>
            <button
              type="button"
              aria-label={`Sort by date${sort.key === "modified" ? `, currently ${sort.direction === "asc" ? "ascending" : "descending"}` : ""}`}
              onClick={() => changeSort("modified")}
            >
              Date
              {sort.key === "modified" && (sort.direction === "asc"
                ? <ArrowUp size={12} strokeWidth={1.75} aria-hidden="true" />
                : <ArrowDown size={12} strokeWidth={1.75} aria-hidden="true" />)}
            </button>
            <button
              className="languageToggle"
              type="button"
              aria-expanded={!languageColumnCollapsed}
              aria-label={`${languageColumnCollapsed ? "Show" : "Hide"} language column`}
              title={`${languageColumnCollapsed ? "Show" : "Hide"} language column`}
              onClick={() => setLanguageColumnCollapsed((collapsed) => !collapsed)}
            >
              <span className="languageToggleLabel">Language</span>
              <span className="languageToggleIcons" aria-hidden="true">
                <PanelRightClose className="languageToggleCloseIcon" size={15} strokeWidth={1.75} />
                <PanelRightOpen className="languageToggleOpenIcon" size={15} strokeWidth={1.75} />
              </span>
            </button>
          </div>
          {loading && (
            <div className="loadingRows" role="status" aria-label="Loading this directory">
              {Array.from({ length: FILE_LIST_SKELETON_ROWS }, (_, index) => (
                <div className="row loadingRow" key={index} aria-hidden="true">
                  <span className="name">
                    <span className="skeleton skeletonIcon" />
                    <span className="skeleton skeletonName" />
                  </span>
                  <span className="skeleton skeletonSize" />
                  <span className="skeleton skeletonDate" />
                  <span className="skeleton skeletonLanguage languageCell" />
                </div>
              ))}
            </div>
          )}
          {!loading && entries.length === 0 && <div className="empty">No supported videos or folders here.</div>}
          {!loading && entries.length > 0 && visibleEntries.length === 0 && <div className="empty">No matches in this folder.</div>}
          {!loading && visibleEntries.map((entry) => entry.type === "directory" ? (
            <button type="button" className="row folder" key={entry.path} onClick={() => void loadDirectory(entry.path)}>
              <span className="name"><i aria-hidden="true"><Folder size={16} strokeWidth={1.75} /></i><span className="fileName">{entry.name}</span></span><span>Folder</span><span>{entry.modified ? new Date(entry.modified).toLocaleDateString() : "—"}</span><span className="languageCell" aria-hidden="true">—</span>
            </button>
          ) : (() => {
            const embedded = embeddedMetadata[entry.path];
            const sidecars = entry.subtitles ?? [];
            return (
            <label className={`row ${selected.includes(entry.path) ? "selected" : ""}`} key={entry.path}>
              <span className="name">
                <span className="checkboxWrap">
                  <input
                    type="checkbox"
                    value={entry.path}
                    checked={selected.includes(entry.path)}
                    onChange={(event) => setSelected((current) => event.target.checked
                      ? [...current, entry.path]
                      : current.filter((path) => path !== entry.path))}
                    disabled={pendingItems.some((item) => item.path === entry.path)}
                  />
                  <span className="checkboxControl" aria-hidden="true"><Check size={12} strokeWidth={2.25} /></span>
                </span>
                <span className="fileName">{entry.name}</span>
              </span>
              <span>{formatSize(entry.size)}</span>
              <span>{entry.modified ? new Date(entry.modified).toLocaleDateString() : "—"}</span>
              <span className="languageCell" aria-hidden={languageColumnCollapsed}>
                {sidecars.map((subtitle) => {
                  const language = getSubtitleLanguage(subtitle.language);
                  return (
                    <span
                      className="languageFlag"
                      role="img"
                      aria-label={`${language.label} sidecar subtitle`}
                      title={`${language.label} · Sidecar · ${subtitle.name}`}
                      key={subtitle.path}
                    >
                      {language.flag}
                    </span>
                  );
                })}
                {embedded?.status === "loading" && (
                  <span className="skeleton languageProbeSkeleton" role="status" aria-label="Loading embedded subtitle languages" />
                )}
                {embedded?.status === "available" && embedded.languages.map((code, index) => {
                  const language = getSubtitleLanguage(code);
                  return (
                    <span
                      className="languageFlag"
                      role="img"
                      aria-label={`${language.label} embedded subtitle`}
                      title={`${language.label} · Embedded subtitle`}
                      key={`embedded-${index}`}
                    >
                      {language.flag}
                    </span>
                  );
                })}
                {shouldShowLanguageDash(sidecars.length, embedded) && <span aria-label="No subtitle language available">—</span>}
              </span>
            </label>
            );
          })())}
        </div>

        <div className="actions">
          <div className="usage">
            <span className="label">Usage</span>
            <span className="usagePill"><strong>{totalTokens.toLocaleString()}</strong> AI tokens</span>
            <span className="usagePill"><strong>{quotaRemaining ?? "—"}</strong> subtitles remaining</span>
          </div>
          <div className="createSplit">
            <button
              className="start"
              type="button"
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
              <summary aria-label="Choose subtitle action" title="Choose subtitle action">
                <ChevronDown size={16} strokeWidth={1.75} aria-hidden="true" />
              </summary>
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
                    <span aria-hidden="true">{actionMode === "subtitles" && option.value === subtitleMode && <Check size={14} strokeWidth={1.75} />}</span>
                    {formatSubtitleModeLabel(option.label, targetLanguageName)}
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
                  <span aria-hidden="true">{actionMode === "rename" && <Check size={14} strokeWidth={1.75} />}</span>Smart rename
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
            <button type="button" aria-label="Close smart rename" onClick={() => renameDialog.current?.close()} disabled={renaming}>
              <X size={18} strokeWidth={1.75} aria-hidden="true" />
            </button>
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
              {renaming ? "Renaming…" : "Rename files"}<ArrowRight size={16} strokeWidth={1.75} aria-hidden="true" />
            </button>
          </div>
        </form>
      </dialog>

      {error && <p className="error" role="alert">{error}</p>}
      <footer>Only files inside the configured {sourceType === "local" ? "local" : "WebDAV"} scan path are visible to this app.</footer>
    </main>
  );
}
