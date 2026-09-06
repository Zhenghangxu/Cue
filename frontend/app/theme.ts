// Keep these aligned with --background in styles/tokens.scss.
export const themeColors = { light: "#f5f7f8", dark: "#101615" };

export const themeScript = `
  (() => {
    let theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    try {
      const stored = localStorage.getItem("cue-theme");
      if (stored === "light" || stored === "dark") theme = stored;
    } catch (_) {}
    document.documentElement.dataset.theme = theme;
  })();
`;
