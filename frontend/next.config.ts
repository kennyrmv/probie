import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    // Analysis takes ~30-40s (5 web searches + Claude). Default is 30s — too short.
    proxyTimeout: 90_000,
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
      {
        source: "/health",
        destination: "http://localhost:8000/health",
      },
    ];
  },
};

export default nextConfig;
