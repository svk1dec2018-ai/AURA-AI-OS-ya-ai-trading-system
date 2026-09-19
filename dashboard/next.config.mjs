const backend = process.env.AURA_BACKEND_URL || "http://127.0.0.1:8766";

const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: backend + "/api/:path*" }];
  },
};

export default nextConfig;
