import { ReactNode, useState } from "react";
import { Maximize2, Minimize2 } from "lucide-react";

/** Cropped height as a fraction of width. Legacy screens put their content in a top band and
 *  leave the rest of the page empty, so showing the whole frame wastes most of the panel. */
const CROPPED_ASPECT = "16 / 7";

/**
 * The window into the session under containment.
 *
 * The page inside is a real capture of the target application and keeps its own appearance — a
 * light legacy app stays light, because the point of evidence is that it is unaltered. What
 * changes is the framing: the capture is cropped to the band that carries content and shown
 * large, rather than letterboxed inside a panel that is then mostly empty. The full untouched
 * frame is one click away.
 */
export default function SessionWindow({
  src,
  url,
  title,
  live,
  aspect = "11/8",
  overlay,
  caption,
  empty,
  strip,
}: {
  src?: string | null;
  url?: string | null;
  title?: string | null;
  live?: boolean;
  aspect?: string;
  overlay?: ReactNode;
  caption?: ReactNode;
  empty?: ReactNode;
  strip?: ReactNode;
}) {
  const [isWhole, setIsWhole] = useState(false);

  return (
    <div className="panel overflow-hidden">
      <div className="flex items-center gap-3 px-3 h-10 border-b border-ink-700 bg-ink-850">
        <span
          className={`lamp ${live ? "text-rose-400" : "text-ink-400"} ${live ? "live" : ""}`}
          title={live ? "A session is running behind this window" : "Recorded capture"}
        >
          {live ? "Live session" : "Captured"}
        </span>
        <span className="flex-1 min-w-0 font-mono text-[12px] text-ink-300 truncate">
          {url || "about:blank"}
        </span>
        {title && <span className="hidden xl:block hint truncate max-w-[28%]">{title}</span>}
        <button
          type="button"
          className="btn !px-2 !py-1"
          aria-pressed={isWhole}
          onClick={() => setIsWhole(!isWhole)}
          title={isWhole ? "Crop to the content band" : "Show the whole captured frame"}
        >
          {isWhole ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
          <span className="hidden sm:inline">{isWhole ? "Crop" : "Whole frame"}</span>
        </button>
      </div>

      {/* The recess: the housing is dark, the glass sits inside it. */}
      <div className="p-2.5 bg-ink-950">
        <div
          className="relative rounded-port overflow-hidden ring-1 ring-ink-600 bg-ink-850"
          style={{ aspectRatio: isWhole ? aspect : CROPPED_ASPECT }}
        >
          {src ? (
            // The overlay is positioned in percentages of the capture, so it has to live in a
            // box that *is* the capture. Cropping with object-cover scales the picture inside
            // this container and leaves the boxes behind, which put every hotspot somewhere the
            // control is not. Cropping is the container's job: the image keeps its own geometry,
            // fills the width, and the overflow is clipped.
            <div className="absolute inset-x-0 top-0">
              <img
                src={src}
                alt={title ?? "captured session"}
                draggable={false}
                className="block w-full"
              />
              {overlay}
            </div>
          ) : (
            <div className="absolute inset-0 grid place-items-center text-[13px] text-ink-400">
              {empty ?? "Nothing captured yet"}
            </div>
          )}
          {/* A faint inner edge so the pale page reads as being behind glass, not pasted on. */}
          <div className="pointer-events-none absolute inset-0 ring-1 ring-inset ring-black/40" />
        </div>
      </div>

      {strip && <div className="px-2.5 pb-2.5 bg-ink-950">{strip}</div>}
      {caption && (
        <div className="px-3 py-2 border-t border-ink-700 font-mono text-[11.5px] text-ink-400 truncate">
          {caption}
        </div>
      )}
    </div>
  );
}
