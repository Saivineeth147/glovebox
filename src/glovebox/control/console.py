"""Minimal operator console: a bare HTML page and JSON API over the OperatorBridge.

It is deliberately small (the brief scopes out a real co-browsing console) but the mechanism
is real: the page shows the open intervention with its context and a live screenshot, lists
the interactive elements of the *same* browser session, and lets the human click/fill/
navigate through them, then hand control back with resume/complete/abort (or approve/decline
for confirmations). It runs in a background thread; every command executes on the automation
thread via the bridge."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .session import OperatorBridge

_PAGE = """<!doctype html><html><head><title>Glovebox operator console</title>
<style>body{font-family:system-ui;margin:16px;display:grid;grid-template-columns:1fr 480px;gap:16px}
pre{white-space:pre-wrap;font-size:12px;background:#f5f5f5;padding:8px;max-height:260px;overflow:auto}
img{max-width:100%;border:1px solid #999} .el{cursor:pointer;font-family:monospace;font-size:12px;padding:2px}
.el:hover{background:#eef} button{margin:2px} #ctx{background:#fff7e0;padding:8px;border:1px solid #e0c060}</style></head>
<body><div>
<h2>Glovebox operator console</h2><div id="ctx">No open intervention.</div>
<h3>Live session</h3><img id="shot" alt="live screenshot"><div id="url"></div>
<h3>Interactive elements (click one, then act)</h3><div id="els"></div>
</div><div>
<h3>Act on the live session</h3>
<div>ref <input id="ref" size="6"> text <input id="text" size="20"></div>
<button onclick="cmd('click')">click</button><button onclick="cmd('fill')">fill</button>
<button onclick="cmd('select')">select</button><button onclick="cmd('press')">press key</button>
<button onclick="cmd('observe')">refresh</button>
<div>url <input id="nav" size="40"><button onclick="cmd('navigate')">navigate</button></div>
<h3>Hand control back</h3>
<button onclick="cmd('resume')">resume automation (retry current step)</button>
<button onclick="cmd('complete')">I finished the flow — verify &amp; complete</button>
<button onclick="cmd('abort')">abort run</button><br>
<button onclick="cmd('approve')">approve irreversible step</button>
<button onclick="cmd('decline')">decline irreversible step</button>
<h3>Log</h3><pre id="log"></pre></div>
<script>
async function refresh(){const r=await fetch('/api/state');const s=await r.json();
 document.getElementById('ctx').innerHTML=s.intervention?`<b>${s.intervention.kind.toUpperCase()}</b> in run ${s.intervention.run_id}<br>capability: ${s.intervention.capability_id||'-'} · goal: ${s.intervention.goal||'-'}<br>step: ${s.intervention.step_id||'-'}<br><b>why:</b> ${s.intervention.reason}<br>owner: <b>${s.owner}</b>`:'No open intervention. Owner: '+s.owner;
 if(s.screenshot){document.getElementById('shot').src='/api/screenshot?t='+Date.now();}
 document.getElementById('url').textContent=s.url||'';
 document.getElementById('els').innerHTML=(s.elements||[]).map(e=>`<div class="el" onclick="pick('${e.split(']')[0].slice(1)}')">${e.replace(/</g,'&lt;')}</div>`).join('');}
function pick(r){document.getElementById('ref').value=r;}
async function cmd(op){const body={op,ref:ref.value,text:text.value,option:text.value,key:text.value||'Enter',url:nav.value};
 const r=await fetch('/api/command',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});
 const j=await r.json();log.textContent=JSON.stringify(j,null,1).slice(0,1500)+"\\n"+log.textContent;refresh();}
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
            return JSONResponse(
                {
                    "owner": "human" if cur else "automation",
                    "intervention": cur.model_dump(mode="json", exclude={"observation_summary"}) if cur else None,
                    "url": obs.url if obs else None,
                    "screenshot": str(obs.screenshot) if obs and obs.screenshot else None,
                    "elements": [e.summary() for e in obs.elements if e.interactive] if obs else [],
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
            args = {k: v for k, v in body.items() if v not in (None, "")}
            return JSONResponse(bridge.submit(op, operator=body.get("operator", "console-user"), **args))

    def start(self) -> OperatorConsole:
        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="warning")
        self._server = uvicorn.Server(config)
        threading.Thread(target=self._server.run, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
