/** Parse API failures safely, including plain-text errors from the Next proxy. */
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
    throw new Error('Cannot reach the dashboard service. Check that the frontend and Python backend are running.');
  }
  const text = await response.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    // Never render raw HTML, server tracebacks, or proxy response text.
    if (!response.ok) {
      throw new Error(routingError(response.status));
    }
    throw new Error(`Dashboard API ${path} returned an invalid response. Restart the backend and retry.`);
  }
  if (!response.ok) {
    if (response.status === 404) throw new Error(routingError(response.status));
    throw new Error(typeof data?.detail === 'string' ? data.detail :
      `Request ${path} failed (HTTP ${response.status}). Check your entries or the backend terminal.`);
  }
  return data;
}
