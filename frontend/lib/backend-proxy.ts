/** Server-side boundary between the Vercel dashboard and persistent Python host.
 * No trading logic, credentials, database, or background worker runs here.
 */
import {resolveBackendOrigin} from './backend-origin.mjs';

type Options = {
  env?: NodeJS.ProcessEnv;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
};
const BODY_LIMIT = 64 * 1024;
function failure(status:number, detail:string) {
  return Response.json({detail}, {status, headers:{'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
}

export async function proxyBackend(request:Request, segments:string[], options:Options = {}) {
  let origin:string;
  try {origin = resolveBackendOrigin(options.env ?? process.env);} catch {
    return failure(503, 'The dashboard is deployed, but its Python backend is not configured. Set BACKEND_URL to a public HTTPS backend origin in Vercel and redeploy.');
  }
  if (!segments.length || segments.some(segment=>!segment || segment === '.' || segment === '..' || /[\\/]/.test(segment))) {
    return failure(400, 'Invalid API path.');
  }
  const url = new URL('/'+segments.map(encodeURIComponent).join('/'), origin);
  url.search = new URL(request.url).search;
  const headers = new Headers();
  // Preserve session isolation and backend CSRF/origin checks. Never forward Host
  // or connection headers, or automatically attach a shared exchange credential.
  for (const name of ['accept','content-type','cookie','origin','x-requested-with','last-event-id']) {
    const value=request.headers.get(name);
    if(value!==null) headers.set(name,value);
  }
  let body:ArrayBuffer|undefined;
  if (!['GET','HEAD'].includes(request.method)) {
    if(Number(request.headers.get('content-length') ?? 0)>BODY_LIMIT) return failure(413,'API request body is too large.');
    body=await request.arrayBuffer();
    if(body.byteLength>BODY_LIMIT) return failure(413,'API request body is too large.');
  }
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),options.timeoutMs ?? 15000);
  try {
    const response=await (options.fetchImpl ?? fetch)(url, {
      method:request.method, headers, body, cache:'no-store', redirect:'manual',
      signal:AbortSignal.any([controller.signal,request.signal]),
    });
    if(response.status>=300 && response.status<400) {
      await response.body?.cancel();
      return failure(502,'The Python backend redirected an API request. Check that BACKEND_URL points directly to the HTTPS backend origin.');
    }
    const outgoing=new Headers({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});
    const contentType=response.headers.get('content-type');
    if(contentType) outgoing.set('content-type',contentType);
    for(const cookie of response.headers.getSetCookie()) outgoing.append('set-cookie',cookie);
    if(contentType?.includes('text/event-stream')) outgoing.set('X-Accel-Buffering','no');
    // Pass the stream directly. Reading text/JSON here would buffer SSE forever.
    return new Response(response.body,{status:response.status,headers:outgoing});
  } catch {
    return controller.signal.aborted
      ? failure(504,'The Python backend did not respond in time. Check its availability and logs, then retry.')
      : failure(502,'Cannot reach the Python backend. Check BACKEND_URL and confirm the backend service is running.');
  } finally {
    // Only bound the wait for response headers; leave established SSE streams
    // open until the client disconnects or the hosting platform reconnects them.
    clearTimeout(timer);
  }
}
