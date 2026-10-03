import type { NextConfig } from "next";

// In Docker: BACKEND_URL=http://backend:8000
// Locally:   defaults to http://127.0.0.1:8000 — BUKAN "localhost": Node bisa memilih ::1
// (IPv6) sementara backend kini hanya mendengar di 127.0.0.1 (ops/start-night.ps1).
const BACKEND_URL = process.env.BACKEND_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/v1/:path*",  destination: `${BACKEND_URL}/api/v1/:path*`  },
      { source: "/health",          destination: `${BACKEND_URL}/health`          },
      { source: "/health/:path*",   destination: `${BACKEND_URL}/health/:path*`   },
      { source: "/ws/:path*",       destination: `${BACKEND_URL}/ws/:path*`       },
    ];
  },
};

export default nextConfig;
