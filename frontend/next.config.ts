import type { NextConfig } from 'next';
import path from 'node:path';
import {resolveBackendOrigin} from './lib/backend-origin.mjs';
const backendOrigin = resolveBackendOrigin();
const config: NextConfig = {
  turbopack: { root: path.resolve('.') },
  async rewrites() { return [{source: '/api/:path*', destination: `${backendOrigin}/:path*`}]; },
  poweredByHeader: false,
};
export default config;
