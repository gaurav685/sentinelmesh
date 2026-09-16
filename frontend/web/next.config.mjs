/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // In dev, proxy the BFF so the browser stays same-origin (the session cookie
  // and CSRF flow depend on it). In prod the reverse proxy does this.
  async rewrites() {
    const target = process.env.SM_API_PROXY_TARGET ?? "http://localhost:8000";
    return [{ source: "/api/:path*", destination: `${target}/api/:path*` }];
  },
  async headers() {
    // Dev mode needs 'unsafe-inline' + 'unsafe-eval' for Next.js hot-reload and source maps
    // Production should use nonces/hashes instead
    const isDev = process.env.NODE_ENV === "development";
    const scriptSrcPolicy = isDev
      ? "'self' 'unsafe-inline' 'unsafe-eval'"
      : "'self'";
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Content-Security-Policy",
            value:
              `default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; ` +
              `script-src ${scriptSrcPolicy}; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'`,
          },
        ],
      },
    ];
  },
};

export default nextConfig;
