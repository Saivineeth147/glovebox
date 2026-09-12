import { useEffect, useState } from "react";
import { api, fmtDate, duration } from "../api";
import { Chip, Empty, PageHeader, Spinner } from "../components/ui";
import { go } from "../App";

export default function Runs() {
  const [runs, setRuns] = useState<any[] | null>(null);
  const [filter, setFilter] = useState("all");
  useEffect(() => {
    const load = () => api.runs().then(setRuns);
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, []);
  if (!runs) return <Spinner />;
  const shown = runs.filter((r) => filter === "all" || r.kind === filter);
  return (
    <>
      <PageHeader title="Runs" subtitle="Every discovery and replay, with its structured evidence."
        action={<div className="flex gap-1 bg-ink-900 border border-ink-800 rounded-lg p-0.5">{["all", "discovery", "replay"].map((f) => <button key={f} onClick={() => setFilter(f)} className={`px-3 py-1 rounded-md text-[12px] font-medium ${filter === f ? "bg-ink-800 text-ink-100" : "text-ink-400 hover:text-ink-200"}`}>{f}</button>)}</div>} />
      <div className="panel overflow-hidden">
        {shown.length === 0 ? <Empty>No runs yet.</Empty> : (
          <table className="w-full text-[13px]">
            <thead className="text-left text-[11px] uppercase tracking-wider text-ink-400 border-b border-ink-800">
              <tr><th className="px-4 py-2.5 font-semibold">Status</th><th className="px-2 py-2.5 font-semibold">Kind</th><th className="px-2 py-2.5 font-semibold">Run</th><th className="px-2 py-2.5 font-semibold">Started</th><th className="px-2 py-2.5 font-semibold">Duration</th><th className="px-2 py-2.5 font-semibold">Evidence</th><th className="px-2 py-2.5 font-semibold">Control</th></tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.run_id} onClick={() => go(`/runs/${r.run_id}`)} className="border-b border-ink-800 last:border-0 hover:bg-ink-850 cursor-pointer">
                  <td className="px-4 py-2.5"><Chip value={r.status} /></td>
                  <td className="px-2 py-2.5"><Chip value={r.kind} /></td>
                  <td className="px-2 py-2.5 min-w-0">
                    <div className="text-ink-100 truncate max-w-[440px]">{r.title.replace(/^(replay|discovery): ?/, "")}</div>
                    <div className="font-mono text-[11px] text-ink-500">{r.run_id}</div>
                  </td>
                  <td className="px-2 py-2.5 text-ink-400 whitespace-nowrap">{fmtDate(r.started_at)}</td>
                  <td className="px-2 py-2.5 text-ink-400 tabular-nums">{duration(r.started_at, r.finished_at) || (r.status === "running" ? <span className="text-amber-300">live</span> : "")}</td>
                  <td className="px-2 py-2.5 text-ink-400">{r.events} events · {r.screenshots} shots</td>
                  <td className="px-2 py-2.5"><Chip value={r.owner} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
