/** Parse API failures safely, including plain-text errors from the Next proxy. */
export class ApiError extends Error {
  status: number;
  constructor(message:string, status:number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export async function requestJson(path: string, method = 'GET', body?: unknown) {
  const hosted = typeof window !== 'undefined' && !['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname);
  const routingError = (status:number) => hosted
    ? `Dashboard API ${path} failed (HTTP ${status}). Check BACKEND_URL in Vercel, redeploy the frontend, and confirm the deployed Python backend exposes this route.`
    : `Dashboard API ${path} failed (HTTP ${status}). Ensure the Python backend is running on port 8000 and check its terminal for errors.`;
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method, credentials: 'include', cache: 'no-store',
      headers: {'Content-Type': 'application/json', 'X-Requested-With': 'CryptoAgent'},
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError('Cannot reach Orbit. Check your connection and try again.', 0);
  }
  const text = await response.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    // Never render raw HTML, server tracebacks, or proxy response text.
    if (!response.ok) {
      throw new ApiError(routingError(response.status), response.status);
    }
    throw new ApiError(`Dashboard API ${path} returned an invalid response. Retry in a moment.`, 502);
  }
  if (!response.ok) {
    if (response.status === 404) throw new ApiError(routingError(response.status), response.status);
    throw new ApiError(typeof data?.detail === 'string' ? data.detail :
      `Request ${path} failed (HTTP ${response.status}). Please try again.`, response.status);
  }
  return data;
}
