import React, { useEffect, useState } from "react";
import { Activity, BookOpen, Compass, LayoutDashboard, ShieldCheck, Sparkles } from "lucide-react";
import Overview from "./pages/Overview";
import Runs from "./pages/Runs";
import RunDetail from "./pages/RunDetail";
import Capabilities from "./pages/Capabilities";
import CapabilityDetail from "./pages/CapabilityDetail";
import Discover from "./pages/Discover";
import Policy from "./pages/Policy";
import { api } from "./api";

export function useRoute() {
  const [hash, setHash] = useState(window.location.hash || "#/");
  useEffect(() => {
    const on = () => setHash(window.location.hash || "#/");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash.replace(/^#/, "");
}

export function go(path: string) {
  window.location.hash = path;
}

const NAV = [
  { path: "/", label: "Overview", icon: LayoutDashboard },
  { path: "/runs", label: "Runs", icon: Activity },
  { path: "/capabilities", label: "Capabilities", icon: BookOpen },
  { path: "/discover", label: "Discover", icon: Compass },
  { path: "/policy", label: "Policy", icon: ShieldCheck },
];

export default function App() {
  const route = useRoute();
  const [ov, setOv] = useState<any>(null);
  useEffect(() => {
    const load = () => api.overview().then(setOv).catch(() => setOv({ target: { up: false } }));
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  let page: React.ReactElement;
  const m = (re: RegExp) => route.match(re);
  if (m(/^\/runs\/([^/]+)$/)) page = <RunDetail runId={m(/^\/runs\/([^/]+)$/)![1]} />;
  else if (route === "/runs") page = <Runs />;
  else if (m(/^\/capabilities\/([^/]+)$/)) page = <CapabilityDetail id={m(/^\/capabilities\/([^/]+)$/)![1]} />;
  else if (route === "/capabilities") page = <Capabilities />;
  else if (route === "/discover") page = <Discover />;
  else if (route === "/policy") page = <Policy />;
  else page = <Overview />;

  const active = (p: string) => (p === "/" ? route === "/" : route.startsWith(p));
  return (
    <div className="h-full flex">
      <aside className="w-[232px] shrink-0 border-r border-ink-800 bg-ink-900/60 flex flex-col">
        <div className="px-4 py-4 flex items-center gap-2.5 border-b border-ink-800">
          <div className="w-7 h-7 rounded-lg bg-accent grid place-items-center"><Sparkles className="w-4 h-4 text-white" /></div>
          <div>
            <div className="text-[14px] font-semibold leading-tight">Glovebox</div>
            <div className="text-[11px] text-ink-400 leading-tight">Studio</div>
          </div>
        </div>
        <nav className="p-2 flex-1">
          {NAV.map(({ path, label, icon: Icon }) => (
            <a key={path} href={`#${path}`} className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] font-medium transition-colors ${active(path) ? "bg-ink-800 text-ink-100" : "text-ink-300 hover:bg-ink-850 hover:text-ink-100"}`}>
              <Icon className="w-4 h-4" /> {label}
              {path === "/runs" && ov?.open_interventions > 0 && <span className="ml-auto chip bg-violet-500/20 text-violet-300 border border-violet-500/30">{ov.open_interventions}</span>}
            </a>
          ))}
        </nav>
        <div className="p-3 border-t border-ink-800 text-[11px] text-ink-400 space-y-1.5">
          <div className="flex items-center gap-2"><span className={`w-1.5 h-1.5 rounded-full ${ov?.target?.up ? "bg-emerald-400" : "bg-rose-400"}`} /> Target {ov?.target?.up ? "reachable" : "offline"}</div>
          <div className="flex items-center gap-2"><span className={`w-1.5 h-1.5 rounded-full ${ov?.has_api_key ? "bg-emerald-400" : "bg-amber-400"}`} /> {ov?.has_api_key ? `Model: ${ov.model}` : "No API key — offline mode"}</div>
          <div className="flex items-center gap-2"><span className="w-1.5 h-1.5 rounded-full bg-ink-500" /> Policy: {ov?.policy ?? "—"}</div>
        </div>
      </aside>
      <main className="flex-1 min-w-0 overflow-auto">
        <div className="max-w-[1400px] mx-auto px-7 py-6 fade-in" key={route}>{page}</div>
      </main>
    </div>
  );
}
