import type { NextConfig } from "next";

// Local dev against the Python API without CORS: API_PROXY_URL=http://localhost:8000 npm run dev
// makes /v1/* on the dev server forward there, the same path the load balancer uses when deployed.
const apiProxy = process.env.API_PROXY_URL?.replace(/\/$/, "");

const nextConfig: NextConfig = {
  // Self-contained server bundle, so the container image doesn't need node_modules.
  output: "standalone",
  async rewrites() {
    return apiProxy ? [{ source: "/v1/:path*", destination: `${apiProxy}/v1/:path*` }] : [];
  },
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
