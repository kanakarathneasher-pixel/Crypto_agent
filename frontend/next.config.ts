import type { NextConfig } from 'next';
import path from 'node:path';
const config: NextConfig = {
  turbopack: { root: path.resolve('.') },
  async rewrites() { return [{source: '/api/:path*', destination: 'http://127.0.0.1:8000/:path*'}]; },
  poweredByHeader: false,
};
export default config;
