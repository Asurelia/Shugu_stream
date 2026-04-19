/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // On the shugu.spoukie.uk subdomain we serve from root. BASE_PATH kept for
  // optional path-based hosting in dev.
  assetPrefix: process.env.BASE_PATH || "",
  basePath: process.env.BASE_PATH || "",
  trailingSlash: false,
  publicRuntimeConfig: {
    root: process.env.BASE_PATH || "",
  },

  // Dev proxy: in production nginx forwards /auth/*, /api/*, /ws/* to the
  // backend uvicorn on port 8701. In dev Next runs alone on 3100, so we
  // replicate that rewrite here. Overrideable via SHUGU_BACKEND_URL.
  async rewrites() {
    const backend = process.env.SHUGU_BACKEND_URL || "http://127.0.0.1:8701";
    return [
      { source: "/auth/:path*", destination: `${backend}/auth/:path*` },
      { source: "/api/:path*",  destination: `${backend}/api/:path*` },
      { source: "/ws/:path*",   destination: `${backend}/ws/:path*` },
    ];
  },
};

module.exports = nextConfig;
