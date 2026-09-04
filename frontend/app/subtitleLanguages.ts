export type SubtitleLanguage = {
  flag: string;
  label: string;
};

const SUBTITLE_LANGUAGES: Record<string, SubtitleLanguage> = {
  "zh-CN": { flag: "🇨🇳", label: "Simplified Chinese" },
  "zh-Hans": { flag: "🇨🇳", label: "Simplified Chinese" },
  "zh-TW": { flag: "🇹🇼", label: "Traditional Chinese" },
  "zh-Hant": { flag: "🇹🇼", label: "Traditional Chinese" },
  en: { flag: "🇬🇧", label: "English" },
  es: { flag: "🇪🇸", label: "Spanish" },
  fr: { flag: "🇫🇷", label: "French" },
  de: { flag: "🇩🇪", label: "German" },
  ja: { flag: "🇯🇵", label: "Japanese" },
  ko: { flag: "🇰🇷", label: "Korean" },
  "pt-BR": { flag: "🇧🇷", label: "Brazilian Portuguese" },
  it: { flag: "🇮🇹", label: "Italian" },
  ru: { flag: "🇷🇺", label: "Russian" },
  ar: { flag: "🇸🇦", label: "Arabic" },
  hi: { flag: "🇮🇳", label: "Hindi" },
  tr: { flag: "🇹🇷", label: "Turkish" },
  pl: { flag: "🇵🇱", label: "Polish" },
  nl: { flag: "🇳🇱", label: "Dutch" },
  id: { flag: "🇮🇩", label: "Indonesian" },
  vi: { flag: "🇻🇳", label: "Vietnamese" },
  th: { flag: "🇹🇭", label: "Thai" },
  uk: { flag: "🇺🇦", label: "Ukrainian" },
  cs: { flag: "🇨🇿", label: "Czech" },
};

const DISPLAY_NAMES = new Intl.DisplayNames(["en"], { type: "language" });

export function normalizeSubtitleLanguage(code?: string | null): string | null {
  if (!code) return null;
  const candidate = code.trim().replaceAll("_", "-");
  if (!candidate || candidate.toLowerCase() === "und") return null;
  try {
    return new Intl.Locale(candidate).toString();
  } catch {
    return null;
  }
}

export function getSubtitleLanguage(code?: string | null): SubtitleLanguage {
  const normalized = normalizeSubtitleLanguage(code);
  if (!normalized) return { flag: "🏳️", label: "Unknown language" };
  return SUBTITLE_LANGUAGES[normalized] ?? {
    flag: "🏳️",
    label: DISPLAY_NAMES.of(normalized) ?? normalized,
  };
}
