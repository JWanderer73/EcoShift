import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The dev-only "N" badge sits over the page corner and can swallow test clicks.
  devIndicators: false,
  cacheComponents: true,
  partialPrefetching: true,
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
