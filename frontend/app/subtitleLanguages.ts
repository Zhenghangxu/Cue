export type SubtitleLanguage = {
  flag: string;
  label: string;
};

const SUBTITLE_LANGUAGES: Record<string, SubtitleLanguage> = {
  "zh-cn": { flag: "🇨🇳", label: "Simplified Chinese" },
  "zh-tw": { flag: "🇹🇼", label: "Traditional Chinese" },
  en: { flag: "🇬🇧", label: "English" },
  es: { flag: "🇪🇸", label: "Spanish" },
  fr: { flag: "🇫🇷", label: "French" },
  de: { flag: "🇩🇪", label: "German" },
  ja: { flag: "🇯🇵", label: "Japanese" },
  ko: { flag: "🇰🇷", label: "Korean" },
  "pt-br": { flag: "🇧🇷", label: "Brazilian Portuguese" },
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

export function getSubtitleLanguage(code?: string | null): SubtitleLanguage {
  if (!code) return { flag: "🏳️", label: "Unknown language" };

  const languages = code.split("+").filter(Boolean).map((part) => (
    SUBTITLE_LANGUAGES[part] ?? { flag: "🏳️", label: part }
  ));
  return {
    flag: languages.map((language) => language.flag).join(""),
    label: languages.map((language) => language.label).join(" & "),
  };
}
