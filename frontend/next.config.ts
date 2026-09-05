import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  allowedDevOrigins: ["127.0.0.1"],
  turbopack: { root: process.cwd() },
};

export default function config(phase: string): NextConfig {
  if (phase !== PHASE_DEVELOPMENT_SERVER) return nextConfig;
  return {
    ...nextConfig,
    output: undefined,
    async rewrites() {
      return {
        beforeFiles: [],
        afterFiles: [
          { source: "/zh/:directory((?!settings(?:/|$)).+)", destination: "/zh/" },
          { source: "/en/:directory((?!settings(?:/|$)).+)", destination: "/en/" },
          { source: "/:directory((?!(?:api|_next|en|zh|settings)(?:/|$)).+)", destination: "/" },
        ],
        fallback: [],
      };
    },
  };
}
