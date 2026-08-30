import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Subtitle Maker",
  description: "Create synchronized Chinese subtitles from WebDAV videos",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

