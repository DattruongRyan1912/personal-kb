import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // a self-contained server for the Docker image (issue 4.3): .next/standalone with only the files it needs
  output: "standalone",
  // the repository's agent instructions live in its root AGENTS.md; next dev must not write its own
  agentRules: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
