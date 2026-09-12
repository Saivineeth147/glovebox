import { ReactNode } from "react";
import { Globe, Radio } from "lucide-react";

/**
 * Presents a screenshot as what it is: a capture of a real browser session under observation.
 * The page inside is the target application and keeps its own look — a light legacy app stays
 * light — but the chrome, bezel and status make it unambiguous that this is a live window, not
 * an empty panel in our UI.
 */
export default function BrowserFrame({ src, url, title, live, aspect = "11/8", overlay, caption, empty }: {
  src?: string | null; url?: string | null; title?: string | null; live?: boolean; aspect?: string;
  overlay?: ReactNode; caption?: ReactNode; empty?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-ink-700 bg-ink-850 overflow-hidden shadow-panel">
      <div className="flex items-center gap-3 px-3 h-9 border-b border-ink-700 bg-ink-800/80">
        <div className="flex gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-[#ff5f57]/90" /><span className="w-2.5 h-2.5 rounded-full bg-[#febc2e]/90" /><span className="w-2.5 h-2.5 rounded-full bg-[#28c840]/90" />
        </div>
        <div className="flex-1 min-w-[140px] flex items-center gap-2 h-6 px-2.5 rounded-md bg-ink-950 border border-ink-700 text-[11.5px] text-ink-300">
          <Globe className="w-3 h-3 text-ink-500 shrink-0" />
          <span className="font-mono truncate">{url || "about:blank"}</span>
        </div>
        {title && <span className="hidden xl:block text-[11px] text-ink-400 truncate max-w-[30%]">{title}</span>}
        <span className={`chip !normal-case !tracking-normal ${live ? "bg-rose-500/15 text-rose-300 border border-rose-500/30" : "bg-ink-700 text-ink-300 border border-ink-600"}`}>
          <Radio className={`w-3 h-3 ${live ? "pulse-dot" : ""}`} /> {live ? "live session" : "captured"}
        </span>
      </div>
      <div className="p-2 bg-ink-950">
        <div className="relative rounded-md overflow-hidden ring-1 ring-black/60 bg-[#1b1e26]" style={{ aspectRatio: aspect }}>
          {src ? <img src={src} className="w-full h-full object-contain" alt={title ?? "browser session"} draggable={false} /> : <div className="absolute inset-0 grid place-items-center text-[12px] text-ink-500">{empty ?? "No capture yet"}</div>}
          {overlay}
          <div className="pointer-events-none absolute inset-0 shadow-[inset_0_0_0_1px_rgba(0,0,0,.35),inset_0_0_40px_rgba(0,0,0,.25)]" />
        </div>
      </div>
      {caption && <div className="px-3 py-1.5 border-t border-ink-800 text-[11px] text-ink-500 font-mono truncate">{caption}</div>}
    </div>
  );
}
