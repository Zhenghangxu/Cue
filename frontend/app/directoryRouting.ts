// Locale prefixes and application routes are reserved at the URL root.
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
