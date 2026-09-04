"use client";

import { type FormEvent, useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";
import { useT } from "next-i18next/client";
import { AppHeader } from "./AppHeader";
import { NativeSelect } from "./NativeSelect";
import { formatSubtitleModeLabel } from "./subtitleOptions";

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
  labelKey: string;
  separatorBefore?: boolean;
  secret?: boolean;
  optional?: boolean;
  type?: string;
  options?: Option[];
  optionKey?: keyof SettingsOptions;
};
const SECTIONS: { titleKey: string; fields: SettingField[] }[] = [
  {
    titleKey: "storage",
    fields: [
      { name: "source_type", labelKey: "mediaSource", optionKey: "source_types" },
      { name: "subtitle_destination", labelKey: "saveSubtitles", optionKey: "subtitle_destinations" },
      { name: "local_scan_path", labelKey: "scanPath", separatorBefore: true },
      { name: "local_output_path", labelKey: "outputFolder", separatorBefore: true },
    ],
  },
  {
    titleKey: "subtitles",
    fields: [
      { name: "target_language", labelKey: "targetLanguage", optionKey: "target_languages" },
      { name: "default_subtitle_mode", labelKey: "defaultMode", optionKey: "subtitle_modes" },
    ],
  },
  {
    titleKey: "webdav",
    fields: [
      { name: "webdav_username", labelKey: "username" },
      { name: "webdav_password", labelKey: "password", secret: true },
      { name: "webdav_endpoint", labelKey: "endpoint" },
      { name: "webdav_scan_path", labelKey: "scanPath" },
    ],
  },
  {
    titleKey: "openSubtitles",
    fields: [
      { name: "opensubtitles_api_key", labelKey: "apiKey", secret: true },
      { name: "opensubtitles_consumer_name", labelKey: "consumerName" },
      { name: "opensubtitles_username", labelKey: "username", optional: true },
      { name: "opensubtitles_password", labelKey: "password", secret: true, optional: true },
    ],
  },
  {
    titleKey: "openAI",
    fields: [
      { name: "openai_base_url", labelKey: "baseUrl", type: "url" },
      { name: "openai_api_key", labelKey: "apiKey", secret: true },
      { name: "openai_model_id", labelKey: "model" },
      {
        name: "openai_reasoning_effort",
        labelKey: "subtitleReasoningEffort",
        options: ["none", "minimal", "low", "medium", "high", "xhigh", "max"].map((value) => ({ value, label: value })),
      },
      {
        name: "openai_rename_reasoning_effort",
        labelKey: "renameReasoningEffort",
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

export function Settings() {
  const { t } = useT("common");
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
  const targetLanguageName = options.target_languages
    .find(({ value }) => value === values.target_language)?.label ?? values.target_language;

  useEffect(() => {
    fetch(`${API}/api/settings`)
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || t("settings.loadError"));
        const settings = body as SettingsResponse;
        setValues(settings.values);
        setStoredSecrets(settings.secrets);
        setOptions(settings.options);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : t("settings.loadError")))
      .finally(() => setLoading(false));
  }, [t]);

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
      if (!response.ok) throw new Error(body.detail || t("settings.saveError"));
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
      setError(reason instanceof Error ? reason.message : t("settings.saveError"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="settingsPage">
      <AppHeader page="settings" />

      <form className="settingsCard" onSubmit={save}>
        <div className="settingsIntro">
          <h2>{t("settings.configuration")}</h2>
          <span>{t("settings.credentialsNotice")}</span>
        </div>
        <div className="settingsGrid">
          {SECTIONS.map((section) => {
            const fields = section.fields.filter((field) => fieldIsVisible(field, values));
            if (!fields.length) return null;
            return <fieldset key={section.titleKey}>
              <legend>{t(`settings.sections.${section.titleKey}`)}</legend>
              {fields.map((field) => (
                <div className={`settingField${field.separatorBefore ? " settingFieldSeparated" : ""}`} key={field.name}>
                  <label htmlFor={field.name}>
                    {t(`settings.fields.${field.labelKey}`)}
                    {field.optional && <small>{t("settings.optional")}</small>}
                  </label>
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
                        <option key={option.value} value={option.value}>
                          {field.name === "default_subtitle_mode"
                            ? formatSubtitleModeLabel(option.label, targetLanguageName)
                            : option.label}
                        </option>
                      ))}
                    </NativeSelect>
                  ) : (
                    <input
                      id={field.name}
                      type={field.secret ? "password" : field.type ?? "text"}
                      value={field.secret ? secretValues[field.name] ?? "" : values[field.name] ?? ""}
                      placeholder={field.secret && storedSecrets[field.name] ? t("settings.secretStored") : ""}
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
                      {t("settings.secretStored")}
                      <span><input
                        type="checkbox"
                        aria-label={t("settings.clearField", { field: t(`settings.fields.${field.labelKey}`) })}
                        checked={clearSecrets.includes(field.name)}
                        onChange={(event) => setClearSecrets((current) => event.target.checked
                          ? [...current, field.name]
                          : current.filter((name) => name !== field.name))}
                      /> {t("settings.clear")}</span>
                    </span>
                  )}
                </div>
              ))}
            </fieldset>;
          })}
        </div>
        <div className="settingsActions">
          <div aria-live="polite">
            {loading && <span>{t("settings.loading")}</span>}
            {message && <span className="success">{message}</span>}
            {error && <span className="settingsError" role="alert">{error}</span>}
          </div>
          <button className="start" type="submit" disabled={loading || saving}>
            {saving ? t("settings.saving") : t("settings.save")}<ArrowRight size={16} strokeWidth={1.75} aria-hidden="true" />
          </button>
        </div>
      </form>
    </main>
  );
}
