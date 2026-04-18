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
};

module.exports = nextConfig;
