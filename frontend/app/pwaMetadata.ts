import type { Metadata } from "next";

export const pwaMetadata: Metadata = {
  applicationName: "Cue",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "Cue", statusBarStyle: "default" },
  icons: {
    icon: [{ url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
    apple: [{ url: "/icons/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
};
