import type { NextConfig } from "next";

// In Docker: BACKEND_URL=http://backend:8000
// Locally:   defaults to http://localhost:8000
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

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
