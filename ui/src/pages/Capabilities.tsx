import { useEffect, useState } from "react";
import { api, fmtDate } from "../api";
import { Chip, Empty, PageHeader, Spinner, Panel, Code } from "../components/ui";
import { go } from "../App";

export default function Capabilities() {
  const [caps, setCaps] = useState<any[] | null>(null);
  const [tools, setTools] = useState<any[] | null>(null);
  useEffect(() => { api.capabilities().then(setCaps); }, []);
  if (!caps) return <Spinner />;
  return (
    <>
      <PageHeader title="Capabilities" subtitle="Recorded flows an agent can invoke by name. Each one is a typed contract with a review state." action={<button className="btn" onClick={() => (tools ? setTools(null) : api.tools().then(setTools))}>{tools ? "Hide" : "Show"} as agent tools</button>} />
      {tools && <Panel title="Tool definitions (Claude function-calling format, from the catalog)" className="mb-4"><Code className="max-h-80">{JSON.stringify(tools, null, 2)}</Code></Panel>}
      {caps.length === 0 ? <Empty>No capabilities yet. Run a discovery.</Empty> : (
        <div className="grid md:grid-cols-2 gap-3">
          {caps.map((c) => (
            <div key={c.id} onClick={() => go(`/capabilities/${c.id}`)} className="panel p-4 cursor-pointer hover:border-ink-600 transition-colors">
              <div className="flex items-center gap-2 mb-1.5"><span className="font-mono text-[12px] text-ink-400">{c.id}@{c.version}</span><Chip value={c.review.status} /><Chip value={c.max_risk} /></div>
              <div className="text-[15px] font-semibold">{c.title}</div>
              <p className="text-[13px] text-ink-300 mt-1 line-clamp-2">{c.description}</p>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink-400 mt-3">
                <span>{c.steps.length} steps</span><span>in: {c.inputs.map((p: any) => p.name).join(", ") || "—"}</span><span>out: {c.outputs.map((o: any) => o.name).join(", ") || "—"}</span>
                <span>outcomes: {c.outcomes.map((o: any) => o.code).join(", ") || "—"}</span>
                <span>confidence: {c.confidence == null ? "—" : `${Math.round(c.confidence * 100)}% (${c.review.replays})`}</span>
              </div>
              <div className="text-[11px] text-ink-500 mt-2">recorded {fmtDate(c.provenance.recorded_at)} by {c.provenance.model} · tenant {c.app.tenant}</div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
