import { useEffect, useState } from "react";
import { api } from "../api";
import { Panel, KV, Code, Spinner, PageHeader, Chip } from "../components/ui";

export default function Policy() {
  const [p, setP] = useState<any>(null);
  useEffect(() => { api.policy().then(setP); }, []);
  if (!p) return <Spinner />;
  const pol = p.policy;
  return (
    <>
      <PageHeader title="Policy" subtitle={<span>Guardrails enforced in front of every action, whether the decision came from the model or from an approved artifact. <span className="font-mono">{p.path}</span></span>} />
      <div className="grid lg:grid-cols-2 gap-4">
        <div className="space-y-4">
          <Panel title="Allowlist">
            <KV rows={[["origins", <div className="font-mono text-[12px] space-y-0.5">{pol.allowed_origins.map((o: string) => <div key={o}>{o}</div>)}</div>], ["allowed paths", <div className="font-mono text-[12px] space-y-0.5">{pol.allowed_path_patterns.map((o: string) => <div key={o}>{o}</div>)}</div>], ["denied paths", <div className="font-mono text-[12px] space-y-0.5 text-rose-300">{pol.denied_path_patterns.map((o: string) => <div key={o}>{o}</div>)}</div>], ["actions", <div className="flex flex-wrap gap-1">{pol.allowed_actions.map((a: string) => <span key={a} className="chip bg-ink-800 text-ink-200 border border-ink-700 !normal-case">{a}</span>)}</div>]]} />
          </Panel>
          <Panel title="Risk model">
            <KV rows={[["irreversible steps", <span><Chip value={pol.irreversible_policy === "confirm" ? "confirm" : pol.irreversible_policy === "block" ? "blocked" : "automation"} /> <span className="text-ink-400 ml-2">{pol.irreversible_policy === "confirm" ? "human approval during discovery; refused unattended" : pol.irreversible_policy}</span></span>], ["unattended ceiling", <Chip value={pol.max_risk_unattended} />], ["draft artifacts", pol.require_approved_for_replay ? "refused for replay until approved" : "allowed"], ["limits", `${pol.max_steps} steps · ${pol.step_timeout_s}s/step · ${pol.run_timeout_s}s/run`]]} />
            <div className="grid grid-cols-3 gap-2 mt-4 text-[12px]">
              {[["read", "observe, extract, assert, navigate", "always"], ["reversible", "type, select, open a form, click a link", "unattended ok"], ["irreversible", "submit that creates/posts/deletes, confirm a mutation", "human confirms"]].map(([r, ex, rule]) => <div key={r} className="rounded-lg border border-ink-800 p-3"><Chip value={r} /><div className="text-ink-300 mt-2">{ex}</div><div className="text-ink-500 mt-1">{rule}</div></div>)}
            </div>
          </Panel>
          <Panel title="Redaction">
            <p className="text-[13px] text-ink-300">Registered secrets (credentials, sensitive inputs and outputs) are replaced with labelled fingerprints before anything is written. Built-in patterns: API keys, bearer tokens, card numbers, US SSNs, <span className="font-mono">password=</span>, session cookies.{pol.redact_patterns.length ? ` Extra: ${pol.redact_patterns.join(", ")}` : ""}</p>
          </Panel>
        </div>
        <Panel title="policies/default.yaml"><Code className="max-h-[70vh]">{p.raw}</Code></Panel>
      </div>
    </>
  );
}
