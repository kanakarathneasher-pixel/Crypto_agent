import {ApiError, requestJson} from './api.ts';

export type OrbitUser = {id:number; username:string; guest:boolean};
type Progress = (message:string)=>void;
type Request = typeof requestJson;
const wait = (milliseconds:number)=>new Promise<void>(resolve=>setTimeout(resolve,milliseconds));

/** Only readiness GETs are retried. Account creation and commands run once. */
export async function connectWorkspace(progress:Progress = ()=>{}, request:Request = requestJson,
                                       delay = wait):Promise<OrbitUser> {
  for(let attempt=0; attempt<5; attempt++) {
    progress(attempt===0?'Connecting to your workspace…':'Waking your workspace. This can take about a minute…');
    try {
      const health=await request('/health');
      if(health.status!=='ok') throw new ApiError('Your workspace is starting.',502);
      break;
    } catch(error) {
      const temporary=error instanceof ApiError && [0,502,504].includes(error.status);
      if(!temporary || attempt===4) throw error;
      await delay(2000);
    }
  }
  progress('Opening your account…');
  return request('/auth/guest','POST');
}

// Strict Mode mounts twice in development. Share startup until it completes.
let pending:Promise<OrbitUser>|null=null;
export function openWorkspace(progress:Progress) {
  if(!pending) pending=connectWorkspace(progress).finally(()=>{pending=null;});
  return pending;
}
