import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  typedRoutes: false,
  outputFileTracingRoot: path.resolve(__dirname, ".."),
};

export default nextConfig;