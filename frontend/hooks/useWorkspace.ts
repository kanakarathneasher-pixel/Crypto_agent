'use client';
import {useCallback, useEffect, useRef, useState} from 'react';
import {ApiError, requestJson} from '../lib/api';
import {openWorkspace, type OrbitUser} from '../lib/workspace';
import {DASHBOARD_REFRESH_MS, type Dashboard} from '../lib/dashboard';

export function useWorkspace(accountOnly:boolean) {
  const [user,setUser]=useState<OrbitUser|null>(null);
  const [checking,setChecking]=useState(true);
  const [message,setMessage]=useState('Connecting to your workspace…');
  const [connectionError,setConnectionError]=useState('');
  const [data,setData]=useState<Dashboard|null>(null);
  const [refreshError,setRefreshError]=useState('');
  const [lastUpdated,setLastUpdated]=useState<Date|null>(null);
  const [expired,setExpired]=useState(false);
  const pending=useRef<Promise<Dashboard>|null>(null);

  const refresh=useCallback(():Promise<Dashboard>=>{
    if(!pending.current) {
      pending.current=requestJson('/dashboard').then((next:Dashboard)=>{
        setData(next);setRefreshError('');setLastUpdated(new Date());return next;
      }).catch(error=>{
        setRefreshError(error instanceof ApiError && error.status===401
          ? 'Your session has expired. Reconnect to continue.' : error.message);
        if(error instanceof ApiError && error.status===401) setExpired(true);
        throw error;
      }).finally(()=>{pending.current=null;});
    }
    return pending.current;
  },[]);

  useEffect(()=>{
    let active=true;
    openWorkspace(value=>{if(active) setMessage(value);})
      .then(value=>{if(active) setUser(value);})
      .catch(error=>{if(active) setConnectionError(error.message);})
      .finally(()=>{if(active) setChecking(false);});
    return ()=>{active=false;};
  },[]);

  useEffect(()=>{
    if(!user || accountOnly || expired) return;
    const update=()=>{
      if(document.visibilityState==='visible') void refresh().catch(()=>{});
    };
    update();
    const timer=setInterval(update,DASHBOARD_REFRESH_MS);
    document.addEventListener('visibilitychange',update);
    return ()=>{clearInterval(timer);document.removeEventListener('visibilitychange',update);};
  },[user,accountOnly,expired,refresh]);

  return {user,checking,message,connectionError,data,refresh,refreshError,lastUpdated,expired};
}
