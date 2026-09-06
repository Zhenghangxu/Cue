"use client";

import { useId, useRef, useState } from "react";
import { ArrowUp, Folder, FolderOpen, House, X } from "lucide-react";
import { useT } from "next-i18next/client";

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
type FolderListing = { path: string; parent: string | null; folders: { name: string; path: string }[] };

export function LocalFolderPicker({ value, label, disabled, onSelect }: {
  value: string;
  label: string;
  disabled: boolean;
  onSelect: (path: string) => void;
}) {
  const { t } = useT("common");
  const id = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const request = useRef(0);
  const [listing, setListing] = useState<FolderListing | null>(null);
  const [path, setPath] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function browse(nextPath: string) {
    const current = ++request.current;
    setLoading(true);
    setError("");
    setPath(nextPath);
    try {
      const response = await fetch(`${API}/api/local-folders?path=${encodeURIComponent(nextPath.trim())}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || t("folderPicker.error"));
      if (request.current !== current) return;
      setListing(body);
      setPath(body.path);
    } catch (reason) {
      if (request.current !== current) return;
      setListing(null);
      setError(reason instanceof Error ? reason.message : t("folderPicker.error"));
    } finally {
      if (request.current === current) setLoading(false);
    }
  }

  return <>
    <button type="button" className="folderPickerTrigger" disabled={disabled}
      aria-label={t("folderPicker.browseField", { field: label })}
      title={t("folderPicker.browseField", { field: label })}
      onClick={() => { dialog.current?.showModal(); void browse(value); }}>
      <FolderOpen size={18} aria-hidden="true" />
    </button>
    <dialog ref={dialog} className="folderPickerDialog" aria-labelledby={`${id}-title`}
      onClick={(event) => { if (event.target === event.currentTarget) dialog.current?.close(); }}>
      <div className="folderPickerHeader">
        <h2 id={`${id}-title`}>{t("folderPicker.title")}</h2>
        <button type="button" aria-label={t("folderPicker.close")} onClick={() => dialog.current?.close()}><X size={18} aria-hidden="true" /></button>
      </div>
      <p>{t("folderPicker.hint")}</p>
      <label htmlFor={`${id}-path`}>{t("folderPicker.path")}</label>
      <div className="folderPickerPath">
        <input id={`${id}-path`} value={path} disabled={loading} onChange={(event) => setPath(event.target.value)}
          onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); event.stopPropagation(); void browse(path); } }} />
        <button type="button" disabled={loading} onClick={() => void browse(path)}>{t("folderPicker.go")}</button>
      </div>
      <div className="folderPickerToolbar">
        <button type="button" disabled={loading} onClick={() => void browse("")}><House size={16} aria-hidden="true" />{t("folderPicker.home")}</button>
        <button type="button" disabled={loading || !listing?.parent} onClick={() => { if (listing?.parent) void browse(listing.parent); }}><ArrowUp size={16} aria-hidden="true" />{t("folderPicker.parent")}</button>
      </div>
      <div className="folderPickerList" aria-busy={loading}>
        {loading ? <p role="status">{t("folderPicker.loading")}</p> : error ? <p role="alert">{error}</p> : <>
          {listing?.folders.length === 0 && <p>{t("folderPicker.empty")}</p>}
          {listing?.folders.map((folder) => <button type="button" key={folder.path} onClick={() => void browse(folder.path)}><Folder size={18} aria-hidden="true" /><span>{folder.name}</span></button>)}
        </>}
      </div>
      <div className="folderPickerActions">
        <button type="button" onClick={() => dialog.current?.close()}>{t("folderPicker.cancel")}</button>
        <button type="button" className="start" disabled={loading || !listing || path !== listing.path} onClick={() => {
          if (listing) { onSelect(listing.path); dialog.current?.close(); }
        }}>{t("folderPicker.select")}</button>
      </div>
    </dialog>
  </>;
}
