/** Server-only rewrite destination. Do not put credentials in this URL. */
export function resolveBackendOrigin(env = process.env) {
  const hosted = env.VERCEL === '1';
  const configured = env.BACKEND_URL?.trim();
  if (hosted && !configured) {
    throw new Error('Set BACKEND_URL in Vercel to your deployed Python backend HTTPS origin, then redeploy. The frontend cannot use localhost on Vercel.');
  }
  const value = configured || 'http://127.0.0.1:8000';
  let url;
  try {url = new URL(value);} catch {
    throw new Error('BACKEND_URL must be an absolute backend URL, for example https://your-backend.example.com.');
  }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error('BACKEND_URL must contain only an HTTP(S) origin, without credentials, /api, query strings or paths.');
  }
  if (hosted && (url.protocol !== 'https:' || ['localhost', '127.0.0.1', '[::1]', '0.0.0.0'].includes(url.hostname))) {
    throw new Error('Vercel BACKEND_URL must be a public HTTPS backend origin, not localhost.');
  }
  return url.origin;
}
