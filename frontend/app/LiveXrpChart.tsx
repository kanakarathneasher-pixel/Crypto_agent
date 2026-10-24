'use client';
import {useEffect, useMemo, useRef, useState} from 'react';
import {requestJson} from '../lib/api';

type Point = {time:number; price:string};
type History = {points:Point[]; interval_seconds:number; period:string};
type Quote = {point:Point|null; connected:boolean; fresh:boolean};
const formatPrice = (price:number) => price.toLocaleString('en-US',{style:'currency',currency:'USD',minimumFractionDigits:4,maximumFractionDigits:5});
const formatTime = (time:number) => new Date(time).toLocaleString(undefined,{timeZone:'UTC',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'})+' UTC';

export default function LiveXrpChart() {
  const [period,setPeriod] = useState('1D');
  const [history,setHistory] = useState<History|null>(null);
  const [ticks,setTicks] = useState<Point[]>([]);
  const [quote,setQuote] = useState<Quote|null>(null);
  const [error,setError] = useState('');
  const [hover,setHover] = useState<number|null>(null);
  const received = useRef(0);
  useEffect(()=>{
    let active = true;
    setHistory(null); setHover(null); setError('');
    const load = () => requestJson(`/market/chart/history?period=${period}`).then(value=>{
      if(active) {setHistory(value); setError('');}
    }).catch(e=>{if(active) setError(e.message);});
    load();
    const timer = setInterval(load,60000);
    return ()=>{active=false;clearInterval(timer);};
  },[period]);
  useEffect(()=>{
    let active = true, pending = false;
    const apply = (value:Quote) => {
      if(!active) return;
      received.current=Date.now(); setQuote(value);
      if(value.point && value.fresh) setTicks(previous=>{
        const point=value.point!;
        // Keep real observations only, at most one sample per two-second bucket.
        const bucket=Math.floor(point.time/2000);
        const kept=previous.filter(p=>Math.floor(p.time/2000)<bucket);
        return [...kept,point].slice(-6000);
      });
    };
    const stream = new EventSource('/api/market/chart/events',{withCredentials:true});
    stream.addEventListener('price',event=>{try {apply(JSON.parse((event as MessageEvent).data));} catch {setError('Invalid chart feed response.');}});
    stream.onerror=()=>setQuote(previous=>previous?{...previous,connected:false,fresh:false}:null);
    // Poll fallback also handles reverse proxies that buffer event streams.
    const timer=setInterval(async()=>{
      if(Date.now()-received.current<2000 || pending) return;
      pending=true;
      try {apply(await requestJson('/market/chart/latest'));}
      catch {if(active) setQuote(previous=>previous?{...previous,connected:false,fresh:false}:null);}
      finally {pending=false;}
    },2000);
    return ()=>{active=false;stream.close();clearInterval(timer);};
  },[]);
  const points=useMemo(()=>{
    if(!history) return [];
    const last=history.points.at(-1)?.time ?? 0;
    return [...history.points,...ticks.filter(p=>p.time>last)];
  },[history,ticks]);
  const prices=points.map(p=>Number(p.price));
  const low=Math.min(...prices), high=Math.max(...prices), spread=high-low || high*.001 || 1;
  const first=points[0]?.time ?? 0, last=points.at(-1)?.time ?? first+1;
  const x=(time:number)=>20+(time-first)/Math.max(1,last-first)*860;
  const y=(price:number)=>220-(price-low)/spread*180;
  const path=points.map((p,i)=>`${i===0 || p.time-points[i-1].time>(history?.interval_seconds ?? 300)*1500?'M':'L'}${x(p.time)},${y(Number(p.price))}`).join(' ');
  const selected=points[hover ?? points.length-1];
  const latestPrice=quote?.point?.price ?? points.at(-1)?.price;
  const change=points.length>1 ? Number(points.at(-1)!.price)/Number(points[0].price)-1 : null;
  return <section className="panel chart-panel xrp-live-panel">
    <div className="panel-heading"><div><h3>XRP price <span className="tiny-tag">USD REFERENCE</span></h3>
      <p>Coinbase public exchange data · Agent market: XRP-USDC</p></div>
      <span className={`pill ${quote?.fresh?'':'quiet'}`}>{quote?.fresh?'LIVE':'RECONNECTING / STALE'}</span></div>
    <div className="xrp-live-summary"><strong>{latestPrice?formatPrice(Number(latestPrice)):'Waiting for Coinbase'}</strong>
      {change!==null&&<span className={change>=0?'positive':'negative'}>{change>=0?'+':''}{(change*100).toFixed(2)}% ({period})</span>}</div>
    <div className="xrp-range-controls" role="group" aria-label="Chart timeframe">{['1H','1D','1W','1M'].map(range=><button key={range} aria-pressed={period===range} className={range===period?'selected':''} onClick={()=>setPeriod(range)}>{range}</button>)}</div>
    {error&&<p className="error" role="alert">{error}</p>}
    {!history ? <div className="chart-empty">Loading Coinbase XRP-USD history…</div> : <>
      <div className="xrp-live-tooltip" aria-live="off">{selected?`${formatPrice(Number(selected.price))} · ${formatTime(selected.time)}`:'No observations available'}</div>
      <div className="xrp-live-plot"><svg viewBox="0 0 900 260" role="img" aria-label={`Live Coinbase XRP-USD price chart, ${period}`} onPointerLeave={()=>setHover(null)} onPointerMove={event=>{
        const rect=event.currentTarget.getBoundingClientRect();
        const target=first+Math.max(0,Math.min(1,((event.clientX-rect.left)/rect.width*900-20)/860))*(last-first);
        let index=0;
        for(let i=1;i<points.length;i++) if(Math.abs(points[i].time-target)<Math.abs(points[index].time-target)) index=i;
        setHover(index);
      }}>
        {[40,130,220].map((level,i)=><g key={level}><line x1="20" x2="880" y1={level} y2={level} stroke="#263038" strokeDasharray="3 5"/><text x="24" y={level-8} fill="#8d9da5" fontSize="10">{formatPrice(high-i*spread/2)}</text></g>)}
        <path d={path} fill="none" stroke="#5284ff" strokeWidth="2.4" vectorEffect="non-scaling-stroke"/>
        {selected&&<><line x1={x(selected.time)} x2={x(selected.time)} y1="30" y2="230" stroke="#718099" strokeDasharray="4 4"/><circle cx={x(selected.time)} cy={y(Number(selected.price))} r="4" fill="#5284ff"/></>}
      </svg></div><div className="chart-dates"><span>{formatTime(first)}</span><span>{formatTime(last)}</span></div>
    </>}
    <div className="chart-footer"><span>Exchange reference curve; Coinbase.com may differ. Missing intervals are not filled.</span>
      <a href="https://www.coinbase.com/price/xrp" target="_blank" rel="noopener noreferrer">Original Coinbase chart ↗</a></div>
  </section>;
}
