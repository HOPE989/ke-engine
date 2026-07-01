import type { NextConfig } from "next";

const backendBaseUrl = process.env.API_BASE_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backendBaseUrl}/api/v1/:path*`
      }
    ];
  }
};

export default nextConfig;
