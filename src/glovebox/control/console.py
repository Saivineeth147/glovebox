"""Operator console: the human side of a handoff.

A single self-contained page (no build step) over the `OperatorBridge` API. It shows the
open intervention with full context, a live screenshot of the *same* browser session with
clickable hotspots for every interactive element, an action bar, the hand-back verbs, and a
timeline of what the human did. Every command executes on the automation thread through the
bridge; this file never touches Playwright.

Endpoints: GET / · GET /api/state · GET /api/screenshot · POST /api/command
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .session import OperatorBridge

_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Glovebox · Operator console</title>
<style>
:root{--bg:#f6f7f9;--panel:#fff;--ink:#14171f;--muted:#66707f;--line:#e4e7ec;--accent:#2f6df6;--accent-ink:#fff;
 --ok:#1a8f5a;--warn:#c77d05;--danger:#d3413b;--human:#7a3ef0;--chip:#eef2f8;--shadow:0 1px 2px rgba(16,24,40,.06),0 8px 24px -12px rgba(16,24,40,.18)}
@media(prefers-color-scheme:dark){:root{--bg:#0f1218;--panel:#171b23;--ink:#e8ebf1;--muted:#9aa4b2;--line:#262c37;--chip:#20262f;--shadow:0 1px 2px rgba(0,0,0,.4),0 12px 32px -12px rgba(0,0,0,.6)}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
header{display:flex;align-items:center;gap:14px;padding:14px 22px;border-bottom:1px solid var(--line);background:var(--panel);position:sticky;top:0;z-index:5}
header h1{font-size:15px;margin:0;font-weight:650;letter-spacing:.2px}header .sub{color:var(--muted);font-size:12px}
.spacer{flex:1}.owner{display:inline-flex;align-items:center;gap:8px;padding:6px 12px;border-radius:999px;font-weight:600;font-size:12px;background:var(--chip)}
.owner .dot{width:8px;height:8px;border-radius:50%;background:var(--ok)}.owner.human .dot{background:var(--human);box-shadow:0 0 0 4px rgba(122,62,240,.18)}
main{display:grid;grid-template-columns:minmax(0,1fr) 380px;gap:18px;padding:18px 22px;max-width:1600px;margin:0 auto}
@media(max-width:1000px){main{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);padding:16px 18px}
.card h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:0 0 10px;font-weight:650}
.stack{display:flex;flex-direction:column;gap:16px}
.badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase}
.badge.stuck{background:#fff1d6;color:#8a5400}.badge.confirm{background:#e6ecff;color:#2646a8}.badge.blocked{background:#fde3e1;color:#8f2420}
@media(prefers-color-scheme:dark){.badge.stuck{background:#3a2b08;color:#f4c15a}.badge.confirm{background:#1c2a52;color:#9fb6ff}.badge.blocked{background:#4a1a18;color:#ff9d97}}
.reason{font-size:16px;font-weight:600;margin:8px 0 10px}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:13px}.kv dt{color:var(--muted)}.kv dd{margin:0;font-variant-numeric:tabular-nums;word-break:break-all}
.empty{color:var(--muted);font-size:13px}
.live{position:relative;border-radius:10px;overflow:hidden;border:1px solid var(--line);background:#000;aspect-ratio:11/8}
.live img{display:block;width:100%;height:100%;object-fit:contain}
.hot{position:absolute;border:1.5px solid rgba(47,109,246,.75);background:rgba(47,109,246,.10);border-radius:3px;cursor:pointer;transition:background .12s}
.hot:hover{background:rgba(47,109,246,.28)}.hot.sel{border-color:var(--human);background:rgba(122,62,240,.28);box-shadow:0 0 0 2px rgba(122,62,240,.35)}
.url{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:var(--muted);margin-top:8px;word-break:break-all}
.els{max-height:260px;overflow:auto;border:1px solid var(--line);border-radius:10px;margin-top:10px}
.el{display:flex;gap:10px;align-items:center;padding:7px 10px;border-bottom:1px solid var(--line);cursor:pointer;font-size:13px}
.el:last-child{border-bottom:0}.el:hover{background:var(--chip)}.el.sel{background:rgba(122,62,240,.12)}
.el .ref{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--muted);min-width:34px}.el .role{color:var(--muted);font-size:12px;min-width:64px}
.el .fr{margin-left:auto;font-size:11px;color:var(--muted)}
.sel-card{background:var(--chip);border-radius:10px;padding:10px 12px;font-size:13px;min-height:44px}
input[type=text]{width:100%;padding:9px 11px;border:1px solid var(--line);border-radius:9px;background:var(--panel);color:var(--ink);font:inherit}
.row{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
button{font:inherit;font-weight:600;border:1px solid var(--line);background:var(--panel);color:var(--ink);padding:8px 12px;border-radius:9px;cursor:pointer}
button:hover{border-color:var(--accent)}button.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
button.ok{background:var(--ok);border-color:var(--ok);color:#fff}button.danger{background:var(--danger);border-color:var(--danger);color:#fff}
button.human{background:var(--human);border-color:var(--human);color:#fff}button:disabled{opacity:.45;cursor:not-allowed}
.verb{display:flex;gap:12px;align-items:flex-start;padding:10px 0;border-top:1px solid var(--line)}.verb:first-of-type{border-top:0}
.verb button{min-width:112px}.verb p{margin:0;font-size:12.5px;color:var(--muted)}
.tl{list-style:none;margin:0;padding:0;max-height:300px;overflow:auto}.tl li{display:flex;gap:10px;padding:7px 0;border-bottom:1px solid var(--line);font-size:13px}
.tl time{color:var(--muted);font-variant-numeric:tabular-nums;font-size:12px;min-width:62px}.tl .who{color:var(--human);font-weight:600}
.toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:10px 16px;border-radius:10px;font-size:13px;opacity:0;transition:opacity .2s;pointer-events:none}
.toast.show{opacity:1}
.who-input{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted)}.who-input input{width:150px;padding:6px 9px}
kbd{font:11px ui-monospace,Menlo,monospace;background:var(--chip);border:1px solid var(--line);border-radius:5px;padding:1px 5px}
</style></head><body>
<header>
  <div><h1>Glovebox · Operator console</h1><div class="sub">Human-in-the-loop for a live automation session</div></div>
  <div class="spacer"></div>
  <label class="who-input">You are <input id="who" type="text" placeholder="operator name"></label>
  <div id="owner" class="owner"><span class="dot"></span><span id="ownerText">automation in control</span></div>
</header>
<main>
  <div class="stack">
    <section class="card" id="ctx"><h2>Intervention</h2><div class="empty">No open intervention. Automation is running; this page updates every 2 s.</div></section>
    <section class="card">
      <h2>Live session <span id="liveMeta" style="text-transform:none;letter-spacing:0;font-weight:500"></span></h2>
      <div class="live" id="live"><img id="shot" alt="live screenshot of the automation's browser"></div>
      <div class="url" id="url"></div>
      <div class="els" id="els"></div>
    </section>
  </div>
  <div class="stack">
    <section class="card"><h2>Act on the live session</h2>
      <div class="sel-card" id="selCard">Pick an element on the screenshot or in the list.</div>
      <div class="row"><input id="text" type="text" placeholder="text to type / option to select / key (default Enter)"></div>
      <div class="row">
        <button class="primary" onclick="act('click')">Click</button><button onclick="act('fill')">Fill</button>
        <button onclick="act('select')">Select</button><button onclick="act('press')">Press key</button>
        <button onclick="act('observe')" title="re-observe the page">Refresh</button>
      </div>
      <div class="row"><input id="nav" type="text" placeholder="URL within the allowlist"><button onclick="act('navigate')">Go</button></div>
    </section>
    <section class="card"><h2>Hand control back</h2>
      <div class="verb"><button class="ok" onclick="act('resume')">Resume</button><p>Retry the current step. Use when you cleared the obstacle (dismissed a dialog, fixed a field).</p></div>
      <div class="verb"><button onclick="act('restart')">Restart</button><p>Re-run the flow from the entry step. Use when your fix reset the form or session.</p></div>
      <div class="verb"><button class="human" onclick="act('complete')">Complete</button><p>You finished the flow by hand. Glovebox verifies the success checkpoint and extracts outputs.</p></div>
      <div class="verb"><button class="danger" onclick="act('abort')">Abort</button><p>Stop the run; the caller gets <em>escalated</em> with your note.</p></div>
      <div class="verb" id="confirmVerbs"><button class="ok" onclick="act('approve')">Approve</button><button class="danger" onclick="act('decline')">Decline</button><p>For irreversible steps only: allow or refuse the pending action.</p></div>
    </section>
    <section class="card"><h2>Timeline</h2><ul class="tl" id="tl"><li class="empty">Nothing yet.</li></ul></section>
  </div>
</main>
<div class="toast" id="toast"></div>
<script>
const $=id=>document.getElementById(id);let sel=null,state=null,lastShot=null;
$('who').value=localStorage.getItem('gb-operator')||'';$('who').addEventListener('change',()=>localStorage.setItem('gb-operator',$('who').value));
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function toast(m){const t=$('toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2200)}
function fmt(ts){try{return new Date(ts).toLocaleTimeString([], {hour12:false})}catch(e){return ''}}
async function refresh(){let r;try{r=await fetch('/api/state');state=await r.json()}catch(e){return}
 const human=state.owner==='human';$('owner').classList.toggle('human',human);$('ownerText').textContent=human?'you are in control':'automation in control';
 const i=state.intervention;
 $('ctx').innerHTML='<h2>Intervention</h2>'+(i?`<span class="badge ${i.kind}">${i.kind}</span><div class="reason">${esc(i.reason)}</div>
   <dl class="kv"><dt>Capability</dt><dd>${esc(i.capability_id||'—')}</dd><dt>Goal</dt><dd>${esc(i.goal||'—')}</dd><dt>Step</dt><dd>${esc(i.step_id||'—')}</dd>
   <dt>Run</dt><dd>${esc(i.run_id)}</dd><dt>Opened</dt><dd>${fmt(i.created_at)}</dd></dl>`:'<div class="empty">No open intervention. Automation is running; this page updates every 2 s.</div>');
 $('confirmVerbs').style.display=(i&&i.kind==='confirm')?'':'none';
 document.querySelectorAll('.verb button, .row button').forEach(b=>b.disabled=!human);
 if(state.screenshot&&state.screenshot!==lastShot){lastShot=state.screenshot;$('shot').src='/api/screenshot?t='+Date.now()}
 $('url').textContent=state.url||'';$('liveMeta').textContent=state.elements?` · ${state.elements.length} interactive elements`:'';
 drawHotspots();
 $('els').innerHTML=(state.elements||[]).map(e=>`<div class="el ${sel===e.ref?'sel':''}" data-ref="${e.ref}"><span class="ref">${e.ref}</span><span class="role">${esc(e.role)}</span><span>${esc(e.name||e.label||e.text||'')}</span><span class="fr">${esc(e.frame||'top')}</span></div>`).join('')||'<div class="empty" style="padding:10px">No elements observed yet.</div>';
 document.querySelectorAll('.el').forEach(d=>d.onclick=()=>pick(d.dataset.ref));
 const acts=(state.actions||[]);$('tl').innerHTML=acts.length?acts.slice().reverse().map(a=>`<li><time>${fmt(a.ts)}</time><span class="who">${esc(a.operator)}</span><span>${esc(a.op)} ${esc(a.target?a.target.description:(a.url||a.key||''))}${a.value?` ← "${esc(a.value)}"`:''}</span></li>`).join(''):'<li class="empty">Nothing yet.</li>';}
function drawHotspots(){document.querySelectorAll('.hot').forEach(h=>h.remove());if(!state||!state.viewport)return;const [vw,vh]=state.viewport;const live=$('live');
 (state.elements||[]).forEach(e=>{const [x,y,w,h]=e.box;if(w<=0||h<=0)return;const d=document.createElement('div');d.className='hot'+(sel===e.ref?' sel':'');
  d.style.left=(100*x/vw)+'%';d.style.top=(100*y/vh)+'%';d.style.width=(100*w/vw)+'%';d.style.height=(100*h/vh)+'%';d.title=`${e.ref} ${e.role} ${e.name||''}`;d.onclick=()=>pick(e.ref);live.appendChild(d)})}
function pick(ref){sel=ref;const e=(state.elements||[]).find(x=>x.ref===ref);$('selCard').innerHTML=e?`<b>${esc(e.role)}</b> ${esc(e.name||e.label||e.text||'')} <span style="color:var(--muted)">· ${e.ref} · frame ${esc(e.frame||'top')}${e.name_attr?' · name='+esc(e.name_attr):''}</span>${e.options&&e.options.length?`<div style="margin-top:4px;color:var(--muted)">options: ${esc(e.options.join(', '))}</div>`:''}`:'Pick an element.';
 document.querySelectorAll('.el').forEach(d=>d.classList.toggle('sel',d.dataset.ref===ref));drawHotspots()}
async function act(op){const body={op,operator:$('who').value||'console-user'};const t=$('text').value;
 if(['click','fill','select','press'].includes(op)){if(!sel&&op!=='press'){toast('Pick an element first');return}if(sel)body.ref=sel;
  if(op==='fill')body.text=t;if(op==='select')body.option=t;if(op==='press')body.key=t||'Enter'}
 if(op==='navigate'){body.url=$('nav').value;if(!body.url){toast('Enter a URL');return}}
 if(op==='abort'||op==='decline')body.note=prompt('Note for the run log (optional)')||undefined;
 const r=await fetch('/api/command',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});const j=await r.json();
 toast(j.ok?(j.resolution?`Control handed back: ${j.resolution}`:`${op} done`):(j.error||'failed'));if(['click','navigate','fill','select','press','resume','restart','complete','abort','approve','decline'].includes(op))sel=null;refresh()}
document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT')return;if(e.key==='r')act('observe')});
refresh();setInterval(refresh,2000);
</script></body></html>"""


class OperatorConsole:
    def __init__(self, bridge: OperatorBridge, host: str = "127.0.0.1", port: int = 8790) -> None:
        self.bridge = bridge
        self.host, self.port = host, port
        self.app = FastAPI(title="Glovebox operator console", docs_url=None)
        self._server: uvicorn.Server | None = None
        self._register()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def _register(self) -> None:
        bridge = self.bridge

        @self.app.get("/", response_class=HTMLResponse)
        def index() -> str:
            return _PAGE

        @self.app.get("/api/state")
        def state() -> JSONResponse:
            obs = bridge.last_observation
            cur = bridge.current
            elements = (
                [
                    {
                        "ref": e.ref,
                        "role": e.role,
                        "name": e.name,
                        "label": e.label,
                        "text": e.text[:80],
                        "name_attr": e.name_attr,
                        "frame": "/".join(e.frame),
                        "box": list(e.page_box),
                        "options": e.options,
                        "summary": e.summary(),
                    }
                    for e in obs.elements
                    if e.interactive
                ]
                if obs
                else []
            )
            return JSONResponse(
                {
                    "owner": "human" if cur else "automation",
                    "intervention": cur.model_dump(mode="json", exclude={"observation_summary"})
                    if cur
                    else None,
                    "url": obs.url if obs else None,
                    "screenshot": str(obs.screenshot) if obs and obs.screenshot else None,
                    "viewport": list(obs.viewport) if obs else None,
                    "elements": elements,
                    "actions": cur.human_actions if cur else [],
                    "history": [
                        i.model_dump(mode="json", exclude={"observation_summary", "human_actions"})
                        for i in bridge.history
                    ],
                }
            )

        @self.app.get("/api/screenshot")
        def screenshot() -> Any:
            obs = bridge.last_observation
            if obs and obs.screenshot and Path(obs.screenshot).exists():
                return FileResponse(str(obs.screenshot), media_type="image/png")
            return JSONResponse({"error": "no screenshot"}, status_code=404)

        @self.app.post("/api/command")
        def command(body: dict[str, Any]) -> JSONResponse:
            op = body.pop("op")
            operator = body.pop("operator", "console-user")
            args = {k: v for k, v in body.items() if v not in (None, "")}
            return JSONResponse(bridge.submit(op, operator=operator, **args))

    def start(self) -> OperatorConsole:
        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="warning")
        self._server = uvicorn.Server(config)
        threading.Thread(target=self._server.run, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
