import { useEffect, useState } from "react";
import { Compass, Plus, X } from "lucide-react";
import { api } from "../api";
import { Panel, PageHeader } from "../components/ui";
import { go } from "../App";

export default function Discover() {
  const [goal, setGoal] = useState("Look up member 100234 and read their current savings balance");
  const [appUrl, setAppUrl] = useState("http://127.0.0.1:8089/");
  const [capId, setCapId] = useState("member_savings_balance");
  const [tenant, setTenant] = useState("alpha");
  const [params, setParams] = useState<[string, string][]>([["member_id", "100234"]]);
  const [offline, setOffline] = useState(false);
  const [hasKey, setHasKey] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.overview().then((o) => { setHasKey(o.has_api_key); setAppUrl(o.target.url + "/"); if (!o.has_api_key) setOffline(true); }); }, []);

  const start = async () => {
    setBusy(true); setErr(null);
    try {
      const job = await api.discover({ goal, app_url: appUrl, capability_id: capId, tenant, params: Object.fromEntries(params.filter(([k]) => k)), offline: offline ? capId : null });
      const wait = async () => { const j = await api.job(job.id); if (j.run_id) go(`/runs/${j.run_id}`); else if (j.status === "error") { setErr(j.error); setBusy(false); } else setTimeout(wait, 300); };
      wait();
    } catch (e: any) { setErr(e.message); setBusy(false); }
  };

  return (
    <>
      <PageHeader title="Discover" subtitle="Give the model a goal. It operates the real UI once, inside policy; the run becomes a reviewable capability." />
      <div className="grid lg:grid-cols-[minmax(0,1fr)_360px] gap-4">
        <Panel title="Goal">
          <div className="space-y-3">
            <textarea className="input min-h-[90px] text-[14px]" value={goal} onChange={(e) => setGoal(e.target.value)} />
            <div className="grid md:grid-cols-3 gap-3">
              <div><div className="label mb-1">Target entry URL</div><input className="input font-mono" value={appUrl} onChange={(e) => setAppUrl(e.target.value)} /></div>
              <div><div className="label mb-1">Capability id</div><input className="input font-mono" value={capId} onChange={(e) => setCapId(e.target.value)} /></div>
              <div><div className="label mb-1">Tenant</div><select className="input" value={tenant} onChange={(e) => setTenant(e.target.value)}><option value="alpha">alpha (Alpine CU)</option><option value="bravo">bravo (Bayview FCU)</option></select></div>
            </div>
            <div>
              <div className="label mb-1">Input parameters <span className="normal-case tracking-normal text-ink-500 font-normal">— the model references these by name; values are substituted and templated</span></div>
              {params.map(([k, v], i) => (
                <div key={i} className="flex gap-2 mb-2"><input className="input font-mono !w-48" placeholder="name" value={k} onChange={(e) => setParams(params.map((p, j) => (j === i ? [e.target.value, p[1]] : p)))} /><input className="input font-mono" placeholder="value" value={v} onChange={(e) => setParams(params.map((p, j) => (j === i ? [p[0], e.target.value] : p)))} /><button className="btn" onClick={() => setParams(params.filter((_, j) => j !== i))}><X className="w-3.5 h-3.5" /></button></div>
              ))}
              <button className="btn" onClick={() => setParams([...params, ["", ""]])}><Plus className="w-3.5 h-3.5" /> parameter</button>
              <div className="text-[12px] text-ink-500 mt-2">Operator credentials are added automatically as sensitive parameters from the environment.</div>
            </div>
            <label className={`flex items-center gap-2 text-[13px] ${!hasKey ? "text-amber-300" : ""}`}><input type="checkbox" checked={offline} onChange={(e) => setOffline(e.target.checked)} /> Offline (scripted decisions, no model){!hasKey ? " — no ANTHROPIC_API_KEY / OPENROUTER_API_KEY detected" : ""}</label>
            {err && <div className="text-[12px] text-rose-300">{err}</div>}
            <button className="btn btn-primary" disabled={busy} onClick={start}><Compass className="w-3.5 h-3.5" /> {busy ? "Starting…" : offline ? "Run scripted discovery" : "Run discovery with Claude"}</button>
          </div>
        </Panel>
        <div className="space-y-4">
          <Panel title="What happens">
            <ol className="text-[13px] text-ink-300 space-y-2 list-decimal pl-4">
              <li>Claude sees a compact element list per frame (plus a screenshot) and acts by reference. Refs expire every observation.</li>
              <li>Every action passes the same allowlist and risk policy replay uses. Irreversible clicks pause for your approval.</li>
              <li>Each action is recorded as a step with several independent locator strategies computed from the live page.</li>
              <li>On finish, the artifact is saved as a <b>draft</b>. Review it, then approve for unattended replay.</li>
            </ol>
          </Panel>
          <Panel title="Tips"><ul className="text-[13px] text-ink-300 space-y-1.5 list-disc pl-4"><li>Name parameters the way an agent would pass them: <span className="font-mono">member_id</span>, not "the number".</li><li>Watch the live run: model decisions stream in the timeline beside the screen.</li><li>If it gets stuck it will escalate to you — the takeover panel appears on the run page.</li></ul></Panel>
        </div>
      </div>
    </>
  );
}
