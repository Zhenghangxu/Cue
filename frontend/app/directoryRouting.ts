// Locale prefixes and application routes are reserved at the URL root.
export const LAST_MEDIA_DIRECTORY_KEY = "cue-last-media-directory";

export function directoryFromPathname(pathname: string): string {
  const segments = pathname.split("/").filter(Boolean);
  if (segments[0] === "en" || segments[0] === "zh") segments.shift();
  if (segments[0] === "browse") segments.shift();
  return segments.map((segment) => {
    const decoded = decodeURIComponent(segment);
    if (decoded === "." || decoded === ".." || /[/\\\0]/.test(decoded)) {
      throw new Error("Invalid directory URL");
    }
    return decoded;
  }).join("/");
}

export function directoryPathname(path: string, locale: string): string {
  const prefix = locale === "zh" ? "/zh" : "";
  // Escape the reserved application names so these folders remain reachable.
  const root = /^(en|zh|settings|api|_next|browse)(\/|$)/.test(path) ? `${prefix}/browse` : prefix;
  return `${root}/${path.split("/").filter(Boolean).map(encodeURIComponent).join("/")}${path ? "/" : ""}`;
}

export function readLastMediaDirectory(storage: Pick<Storage, "getItem">): string {
  try {
    const path = storage.getItem(LAST_MEDIA_DIRECTORY_KEY) ?? "";
    // Only return canonical paths that could have come from a media URL.
    return directoryFromPathname(directoryPathname(path, "en")) === path ? path : "";
  } catch {
    return "";
  }
}

export function rememberMediaDirectory(storage: Pick<Storage, "setItem">, path: string): void {
  try {
    storage.setItem(LAST_MEDIA_DIRECTORY_KEY, path);
  } catch {
    // Browsing should still work when storage is unavailable.
  }
}
