import {proxyBackend} from '../../../lib/backend-proxy';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const maxDuration = 60;

type Context = {params:Promise<{path:string[]}>};
async function handler(request:Request, context:Context) {
  return proxyBackend(request,(await context.params).path);
}
export {handler as GET,handler as POST,handler as PUT,handler as PATCH,handler as DELETE};
