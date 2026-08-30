"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

type FileEntry = {
  name: string;
  path: string;
  type: "directory" | "video";
  size?: number | null;
  modified?: string | null;
};

type Job = {
  id: string;
  path: string;
  status: string;
  message: string;
  error?: string | null;
  result?: {
    outputPath: string;
    sourceLanguage: string;
    release: string;
    moviehashMatch: boolean;
    quota: { remaining?: number | null; resetTimeUtc?: string | null };
    aiUsage: { promptTokens: number; completionTokens: number; totalTokens: number };
  } | null;
};

type Health = {
  ready: boolean;
  configuration: string;
  binaries: { ffmpeg: boolean; ffsubsync: boolean };
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
  const [health, setHealth] = useState<Health | null>(null);
  const [path, setPath] = useState("");
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [selected, setSelected] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadDirectory = useCallback(async (nextPath: string) => {
    setLoading(true);
    setError("");
    setSelected("");
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
        if (value.ready) void loadDirectory("");
        else setLoading(false);
      })
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : "Backend is unavailable");
        setLoading(false);
      });

    const remembered = sessionStorage.getItem("subtitle-maker-job");
    if (remembered) {
      api<Job>(`/api/jobs/${remembered}`).then(setJob).catch(() => sessionStorage.removeItem("subtitle-maker-job"));
    }
  }, [loadDirectory]);

  useEffect(() => {
    if (!job || TERMINAL.has(job.status)) return;
    const timer = window.setTimeout(() => {
      api<Job>(`/api/jobs/${job.id}`).then(setJob).catch((reason) => setError(String(reason)));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [job]);

  const crumbs = useMemo(() => {
    const parts = path ? path.split("/") : [];
    return [
      { name: "Media", path: "" },
      ...parts.map((name, index) => ({ name, path: parts.slice(0, index + 1).join("/") })),
    ];
  }, [path]);

  async function start() {
    if (!selected) return;
    setError("");
    try {
      const value = await api<{ jobId: string }>("/api/jobs", {
        method: "POST",
        body: JSON.stringify({ path: selected }),
      });
      sessionStorage.setItem("subtitle-maker-job", value.jobId);
      setJob({ id: value.jobId, path: selected, status: "queued", message: "Waiting to start" });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start the job");
    }
  }

  const busy = Boolean(job && !TERMINAL.has(job.status));

  return (
    <main>
      <header className="hero">
        <div className="mark" aria-hidden="true">字</div>
        <div>
          <p className="eyebrow">LOCAL WEBDAV TOOL</p>
          <h1>Subtitle Maker</h1>
          <p className="lede">Find, synchronize, and translate subtitles without downloading the full video.</p>
        </div>
        <div className={`health ${health?.ready ? "ready" : ""}`}>
          <span aria-hidden="true" />
          {health?.ready ? "Ready" : "Setup needed"}
        </div>
      </header>

      {health && !health.ready && (
        <section className="notice" role="alert">
          <strong>Backend setup is incomplete.</strong>
          <span>{health.configuration}</span>
          {!health.binaries.ffmpeg && <span>FFmpeg is missing.</span>}
          {!health.binaries.ffsubsync && <span>Run <code>uv sync</code> to install ffsubsync.</span>}
        </section>
      )}

      <section className="workspace" aria-label="WebDAV video browser">
        <nav className="breadcrumbs" aria-label="Directory path">
          {crumbs.map((crumb, index) => (
            <span key={crumb.path || "root"}>
              {index > 0 && <b aria-hidden="true">/</b>}
              <button onClick={() => void loadDirectory(crumb.path)} disabled={loading || busy}>
                {crumb.name}
              </button>
            </span>
          ))}
        </nav>

        <div className="table" aria-label="Videos">
          <div className="tableHead">
            <span>Name</span><span>Size</span><span>Modified</span>
          </div>
          {loading && <div className="empty">Loading this directory…</div>}
          {!loading && entries.length === 0 && <div className="empty">No supported videos or folders here.</div>}
          {!loading && entries.map((entry) => entry.type === "directory" ? (
            <button className="row folder" key={entry.path} onClick={() => void loadDirectory(entry.path)} disabled={busy}>
              <span className="name"><i aria-hidden="true">↳</i>{entry.name}</span><span>Folder</span><span>—</span>
            </button>
          ) : (
            <label className={`row ${selected === entry.path ? "selected" : ""}`} key={entry.path}>
              <span className="name">
                <input
                  type="radio"
                  name="video"
                  value={entry.path}
                  checked={selected === entry.path}
                  onChange={() => setSelected(entry.path)}
                  disabled={busy}
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
            <span className="label">Selected video</span>
            <strong>{selected ? selected.split("/").at(-1) : "Choose one file above"}</strong>
          </div>
          <button className="start" onClick={() => void start()} disabled={!selected || busy || !health?.ready}>
            {busy ? "Working…" : "Create subtitles"}<span aria-hidden="true">→</span>
          </button>
        </div>
      </section>

      {job && (
        <section className={`job ${job.status}`} aria-live="polite">
          <div className="jobTop">
            <div>
              <p className="eyebrow">CURRENT JOB</p>
              <h2>{job.status === "completed" ? "Subtitle ready" : job.status === "failed" ? "Could not finish" : job.message}</h2>
            </div>
            <span className="stage">{job.status.replaceAll("_", " ")}</span>
          </div>
          {busy && <div className="progress"><span /></div>}
          {job.error && <p className="jobError">{job.error}</p>}
          {job.result && (
            <dl>
              <div><dt>Uploaded</dt><dd>{job.result.outputPath}</dd></div>
              <div><dt>Source</dt><dd>{job.result.sourceLanguage} · {job.result.release}</dd></div>
              <div><dt>OpenSubtitles remaining</dt><dd>{job.result.quota.remaining ?? "Unknown"}</dd></div>
              <div><dt>AI tokens</dt><dd>{job.result.aiUsage.totalTokens.toLocaleString()}</dd></div>
            </dl>
          )}
        </section>
      )}

      {error && <p className="error" role="alert">{error}</p>}
      <footer>Only files inside the configured WebDAV scan path are visible to this app.</footer>
    </main>
  );
}
