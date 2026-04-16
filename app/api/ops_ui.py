"""Minimal ops UI (Phase 5 Blocker 3) — self-contained HTML page.

Serves /ops which renders a call list + transcript viewer backed by
/api/calls and /api/calls/{id} endpoints. No build step, no Streamlit.

Auth: user provides their Bearer API key in the UI, stored in sessionStorage.
Everything runs in the browser, so credentials never touch the server (except
in standard Authorization header).

For production, front this with an HTTPS reverse proxy and use a tenant-scoped
API key.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

ops_router = APIRouter()


OPS_HTML = r"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"/>
<title>OptiBot Ops</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:0;background:#0b0d12;color:#e5e7eb}
header{padding:16px 24px;border-bottom:1px solid #1f2937;display:flex;align-items:center;gap:16px}
h1{margin:0;font-size:18px;font-weight:600}
.container{display:grid;grid-template-columns:400px 1fr;height:calc(100vh - 60px)}
.sidebar{border-right:1px solid #1f2937;overflow-y:auto}
.detail{overflow-y:auto;padding:24px}
input,button{background:#1f2937;color:#e5e7eb;border:1px solid #374151;padding:6px 10px;border-radius:4px;font-size:14px}
button{cursor:pointer}
button:hover{background:#374151}
.call{padding:12px 16px;border-bottom:1px solid #1f2937;cursor:pointer}
.call:hover{background:#111827}
.call.active{background:#1e3a8a}
.call-mutuelle{font-weight:600}
.call-meta{font-size:12px;color:#9ca3af;margin-top:4px}
.outcome{display:inline-block;padding:2px 8px;border-radius:3px;font-size:11px;margin-right:4px}
.outcome.success,.outcome.all_info_collected{background:#065f46;color:#d1fae5}
.outcome.escalated,.outcome.error{background:#7c2d12;color:#fed7aa}
.outcome.voicemail,.outcome.wrong_mutuelle{background:#78350f;color:#fef3c7}
.turn{margin:12px 0;padding:10px 14px;border-radius:6px;max-width:85%}
.turn.agent{background:#1e3a8a;margin-left:auto}
.turn.user{background:#374151}
.turn.system,.turn.tool{background:#111827;color:#9ca3af;font-size:12px;font-style:italic;text-align:center;max-width:none}
.turn-meta{font-size:11px;opacity:0.6;margin-bottom:4px}
.empty{padding:40px;text-align:center;color:#6b7280}
pre{background:#111827;padding:12px;border-radius:4px;overflow-x:auto;font-size:12px}
audio{width:100%;margin:12px 0}
</style></head>
<body>
<header>
<h1>OptiBot Ops</h1>
<input id="apikey" placeholder="Bearer API key (e.g. opti_...)" style="width:260px"/>
<button onclick="loadCalls()">Refresh</button>
<span id="status"></span>
</header>
<div class="container">
  <div class="sidebar" id="callList"><div class="empty">Enter API key and click Refresh</div></div>
  <div class="detail" id="detail"><div class="empty">Select a call to view details</div></div>
</div>
<script>
const API=location.origin;
function key(){const k=document.getElementById('apikey').value||sessionStorage.getItem('optibot_key');sessionStorage.setItem('optibot_key',k);return k}
async function api(path){
  const r=await fetch(API+path,{headers:{Authorization:'Bearer '+key()}});
  if(!r.ok)throw new Error(r.status+' '+await r.text());
  return r.json();
}
async function loadCalls(){
  const s=document.getElementById('status');s.textContent='Loading...';
  try{
    const d=await api('/api/calls?limit=100');
    const list=document.getElementById('callList');
    list.innerHTML='';
    if(!d.calls||d.calls.length===0){list.innerHTML='<div class="empty">No calls yet</div>';s.textContent='';return}
    d.calls.forEach(c=>{
      const e=document.createElement('div');e.className='call';
      const oc=c.outcome||'pending';
      e.innerHTML=`<div class="call-mutuelle">${c.mutuelle||'—'}</div>
        <div class="call-meta">
          <span class="outcome ${oc}">${oc}</span>
          ${c.duration_seconds?Math.round(c.duration_seconds)+'s':''}
          · ${c.id}
        </div>`;
      e.onclick=()=>{document.querySelectorAll('.call').forEach(x=>x.classList.remove('active'));e.classList.add('active');loadCall(c.id)};
      list.appendChild(e);
    });
    s.textContent=d.calls.length+' calls';
  }catch(e){s.textContent='Error: '+e.message}
}
async function loadCall(id){
  const el=document.getElementById('detail');el.innerHTML='<div class="empty">Loading...</div>';
  try{
    const d=await api('/api/calls/'+id);
    let html=`<h2>${d.call.mutuelle||'Unknown'} — ${d.call.id}</h2>`;
    html+='<pre>'+JSON.stringify({outcome:d.call.outcome,duration_seconds:d.call.duration_seconds,tools_called:d.call.tools_called,extracted_data:d.call.extracted_data},null,2)+'</pre>';
    if(d.recording&&d.recording.storage_url){html+=`<audio controls src="${d.recording.storage_url}"></audio>`}
    html+='<h3>Transcript</h3>';
    if(!d.transcript||d.transcript.length===0){html+='<div class="empty">No transcript captured</div>'}
    else{d.transcript.forEach(t=>{html+=`<div class="turn ${t.role}"><div class="turn-meta">${t.role} · ${t.ts_ms}ms</div>${escapeHtml(t.text)}</div>`})}
    el.innerHTML=html;
  }catch(e){el.innerHTML='<div class="empty">Error: '+e.message+'</div>'}
}
function escapeHtml(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
// Auto-load saved key
const saved=sessionStorage.getItem('optibot_key');
if(saved){document.getElementById('apikey').value=saved;loadCalls()}
</script></body></html>"""


@ops_router.get("/ops", response_class=HTMLResponse)
async def ops_page():
    return HTMLResponse(content=OPS_HTML)
