"use client";

import { type FormEvent, useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";
import { AppHeader } from "../AppHeader";
import { NativeSelect } from "../NativeSelect";

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
type Option = { value: string; label: string };
type SettingsOptions = {
  target_languages: Option[];
  subtitle_modes: Option[];
  source_types: Option[];
  subtitle_destinations: Option[];
};
type SettingField = {
  name: string;
  label: string;
  separatorBefore?: boolean;
  secret?: boolean;
  optional?: boolean;
  type?: string;
  options?: Option[];
  optionKey?: keyof SettingsOptions;
};
const SECTIONS: { title: string; fields: SettingField[] }[] = [
  {
    title: "Storage",
    fields: [
      { name: "source_type", label: "Media source", optionKey: "source_types" },
      { name: "subtitle_destination", label: "Save subtitles", optionKey: "subtitle_destinations" },
      { name: "local_scan_path", label: "Scan path", separatorBefore: true },
      { name: "local_output_path", label: "Output folder", separatorBefore: true },
    ],
  },
  {
    title: "Subtitles",
    fields: [
      { name: "target_language", label: "Target language", optionKey: "target_languages" },
      { name: "default_subtitle_mode", label: "Default mode", optionKey: "subtitle_modes" },
    ],
  },
  {
    title: "WebDAV",
    fields: [
      { name: "webdav_username", label: "Username" },
      { name: "webdav_password", label: "Password", secret: true },
      { name: "webdav_endpoint", label: "Endpoint" },
      { name: "webdav_scan_path", label: "Scan path" },
    ],
  },
  {
    title: "OpenSubtitles",
    fields: [
      { name: "opensubtitles_api_key", label: "API key", secret: true },
      { name: "opensubtitles_consumer_name", label: "Consumer name" },
      { name: "opensubtitles_username", label: "Username", optional: true },
      { name: "opensubtitles_password", label: "Password", secret: true, optional: true },
    ],
  },
  {
    title: "OpenAI",
    fields: [
      { name: "openai_base_url", label: "Base URL", type: "url" },
      { name: "openai_api_key", label: "API key", secret: true },
      { name: "openai_model_id", label: "Model" },
      {
        name: "openai_reasoning_effort",
        label: "Reasoning effort",
        options: ["none", "minimal", "low", "medium", "high", "xhigh", "max"].map((value) => ({ value, label: value })),
      },
    ],
  },
];

function fieldIsVisible(field: SettingField, values: Record<string, string>) {
  const source = values.source_type ?? "webdav";
  const destination = values.subtitle_destination ?? "source";
  if (field.name.startsWith("webdav_")) return source === "webdav";
  if (field.name === "local_scan_path") return source === "local";
  if (field.name === "local_output_path") return source === "webdav" && destination === "local";
  return true;
}

type SettingsResponse = {
  values: Record<string, string>;
  secrets: Record<string, boolean>;
  options: SettingsOptions;
};

export default function Settings() {
  const [values, setValues] = useState<Record<string, string>>({});
  const [secretValues, setSecretValues] = useState<Record<string, string>>({});
  const [storedSecrets, setStoredSecrets] = useState<Record<string, boolean>>({});
  const [options, setOptions] = useState<SettingsOptions>({
    target_languages: [],
    subtitle_modes: [],
    source_types: [],
    subtitle_destinations: [],
  });
  const [clearSecrets, setClearSecrets] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API}/api/settings`)
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || "Could not load settings");
        const settings = body as SettingsResponse;
        setValues(settings.values);
        setStoredSecrets(settings.secrets);
        setOptions(settings.options);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Could not load settings"))
      .finally(() => setLoading(false));
  }, []);

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    setError("");
    try {
      const response = await fetch(`${API}/api/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values, secrets: secretValues, clear_secrets: clearSecrets }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Could not save settings");
      setStoredSecrets((current) => {
        const next = { ...current };
        for (const [key, value] of Object.entries(secretValues)) if (value) next[key] = true;
        for (const key of clearSecrets) next[key] = false;
        return next;
      });
      setSecretValues({});
      setClearSecrets([]);
      setMessage(body.message);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save settings");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="settingsPage">
      <AppHeader page="settings" />

      <form className="settingsCard" onSubmit={save}>
        <div className="settingsIntro">
          <div><p className="eyebrow">LOCAL CONFIGURATION</p><h2>Configuration</h2></div>
          <span>Saved secret values are never sent back to this page.</span>
        </div>
        <div className="settingsGrid">
          {SECTIONS.map((section) => {
            const fields = section.fields.filter((field) => fieldIsVisible(field, values));
            if (!fields.length) return null;
            return <fieldset key={section.title}>
              <legend>{section.title}</legend>
              {fields.map((field) => (
                <div className={`settingField${field.separatorBefore ? " settingFieldSeparated" : ""}`} key={field.name}>
                  <label htmlFor={field.name}>{field.label}{field.optional && <small>Optional</small>}</label>
                  {field.options || field.optionKey ? (
                    <NativeSelect
                      id={field.name}
                      value={values[field.name] ?? ""}
                      onChange={(event) => setValues((current) => ({
                        ...current,
                        [field.name]: event.target.value,
                        ...(field.name === "source_type" && event.target.value === "local"
                          ? { subtitle_destination: "source" }
                          : {}),
                      }))}
                      disabled={loading || saving}
                    >
                      {(field.options ?? options[field.optionKey!] ?? [])
                        .filter((option) => field.name !== "subtitle_destination"
                          || values.source_type !== "local"
                          || option.value === "source")
                        .map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </NativeSelect>
                  ) : (
                    <input
                      id={field.name}
                      type={field.secret ? "password" : field.type ?? "text"}
                      value={field.secret ? secretValues[field.name] ?? "" : values[field.name] ?? ""}
                      placeholder={field.secret && storedSecrets[field.name] ? "Stored in .env" : ""}
                      onChange={(event) => field.secret
                        ? (setSecretValues((current) => ({ ...current, [field.name]: event.target.value })),
                          setClearSecrets((current) => current.filter((name) => name !== field.name)))
                        : setValues((current) => ({ ...current, [field.name]: event.target.value }))}
                      disabled={loading || saving || clearSecrets.includes(field.name)}
                      required={!field.optional && (!field.secret || !storedSecrets[field.name])}
                      autoComplete={field.secret ? "new-password" : "off"}
                    />
                  )}
                  {field.secret && storedSecrets[field.name] && (
                    <span className="secretState">
                      Stored in .env
                      <span><input
                        type="checkbox"
                        aria-label={`Clear ${field.label}`}
                        checked={clearSecrets.includes(field.name)}
                        onChange={(event) => setClearSecrets((current) => event.target.checked
                          ? [...current, field.name]
                          : current.filter((name) => name !== field.name))}
                      /> Clear</span>
                    </span>
                  )}
                </div>
              ))}
            </fieldset>;
          })}
        </div>
        <div className="settingsActions">
          <div aria-live="polite">
            {loading && <span>Loading settings…</span>}
            {message && <span className="success">{message}</span>}
            {error && <span className="settingsError" role="alert">{error}</span>}
          </div>
          <button className="start" type="submit" disabled={loading || saving}>
            {saving ? "Saving…" : "Save settings"}<ArrowRight size={16} strokeWidth={1.75} aria-hidden="true" />
          </button>
        </div>
      </form>
    </main>
  );
}
