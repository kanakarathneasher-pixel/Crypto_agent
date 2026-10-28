'use client';
import {type FormEvent,useState} from 'react';
import {requestJson as api} from '../../lib/api';

export default function AskOrbit() {
  const [question,setQuestion]=useState('');
  const [chat,setChat]=useState<{role:string;text:string}[]>([]),[chatBusy,setChatBusy]=useState(false);
  async function ask(e: FormEvent) {
    e.preventDefault();if (!question.trim() || chatBusy) return;
    const message = question;setQuestion('');setChat(c => [...c,{role:'You',text:message}]);setChatBusy(true);
    try {const response = await api('/chat','POST',{message});setChat(c => [...c,{role:'Orbit',text:response.answer}]);}
    catch(e) {setChat(c => [...c,{role:'System',text:(e as Error).message}]);}finally {setChatBusy(false);}
  }
  return <section className="panel chat-panel"><div className="panel-heading"><div><h3><span className="spark">✧</span> Ask Orbit</h3><p>Understand your agent using your actual backend data.</p></div><span className="pill quiet">READ ONLY</span></div><div className="chat-messages" aria-live="polite">{!chat.length&&<p className="muted">Try “Why did my agent HOLD?” or “What are my risk limits?”</p>}{chat.map((m,i)=><div className={`chat-message ${m.role==='You'?'from-user':''}`} key={i}><strong>{m.role}</strong><p>{m.text}</p></div>)}{chatBusy&&<p className="muted">Reading your account state…</p>}</div><form className="chat-input" onSubmit={ask}><input aria-label="Ask your trading assistant" placeholder="Ask about your paper portfolio or latest decision…" value={question} onChange={e=>setQuestion(e.target.value)} maxLength={2000}/><button className="primary" disabled={chatBusy||!question.trim()}>Send ↗</button></form><small className="chat-disclaimer">Chat cannot execute trades or change risk limits. Forecasts do not guarantee returns.</small></section>;
}
