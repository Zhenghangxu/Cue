export function formatSubtitleModeLabel(label: string, targetLanguageName?: string) {
  const language = targetLanguageName?.trim();
  return language ? label.replace(/target language/gi, language) : label;
}
