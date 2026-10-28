export default function WorkspaceGate({checking,message,error}:{checking:boolean;message:string;error:string}) {
  return <main className="workspace-gate"><div className="panel workspace-gate-card">
    <span className="eyebrow">ORBIT WORKSPACE</span>
    <h1>{checking?'A moment to connect.':'Let’s reconnect.'}</h1>
    <p role={checking?'status':'alert'}>{checking?message:error||'Your workspace is temporarily unavailable.'}</p>
    {checking?<div className="connection-progress" aria-hidden="true"/>:
      <button className="primary" onClick={()=>window.location.reload()}>Retry connection</button>}
  </div></main>;
}
