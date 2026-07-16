import type { NextConfig } from "next";

const documentApiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:8000";
const chatApiBaseUrl = process.env.CHAT_API_BASE_URL ?? "http://localhost:8001";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/v1/chat/:path*",
        destination: `${chatApiBaseUrl}/api/v1/chat/:path*`
      },
      {
        source: "/api/v1/:path*",
        destination: `${documentApiBaseUrl}/api/v1/:path*`
      }
    ];
  }
};

export default nextConfig;
