/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // On the shugu.spoukie.uk subdomain we serve from root. NEXT_PUBLIC_BASE_PATH
  // kept for optional path-based hosting in dev. Note (Next 16) : read at
  // build time and inlined as a static string in client bundles via the
  // NEXT_PUBLIC_ prefix — `publicRuntimeConfig` was removed in Next 16. To
  // change the base path, rebuild the frontend with the new env value.
  assetPrefix: process.env.NEXT_PUBLIC_BASE_PATH || "",
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || "",
  trailingSlash: false,

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
