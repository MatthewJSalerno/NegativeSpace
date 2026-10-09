import { useLayoutEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { Timeline } from "../api";
import { dateLabel } from "./DatesPanel";

// Room each year label needs on the track; years closer than this to the last label
// shown are left unlabelled, as Immich's scrubber does.
const LABEL_SPACE = 20;

interface Segment { key: string; year: string; top: number; height: number }

// The date scrubber (webui-spec 2; ui-design.md "Page frame"), down the gallery's right
// edge while it is sorted by date: the years with photos, each given room by how many it
// holds, in the gallery's order, with "No date" last. Pointing shows the month under the
// pointer; a click or a drag's release goes there, and a year label goes to that year.
// Labels are buttons, so the keyboard reaches them; Filters › Dates goes to any month.
// It uses the same jump as the Dates tree, so a date the filters hide says so.
export function YearScrubber({ timeline, newestFirst, current, onJump }: {
  timeline: Timeline | null;
  newestFirst: boolean;
  current: string[];
  onJump: (key: string) => void;
}) {
  const track = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState(0);
  const [hover, setHover] = useState<Segment | null>(null);
  const dragging = useRef(false);
  useLayoutEffect(() => {
    const el = track.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setHeight(el.clientHeight));
    observer.observe(el);
    setHeight(el.clientHeight);
    return () => observer.disconnect();
  }, []);

  // Months in gallery order, then the photos with no date, as fractions of the whole.
  const segments = useMemo(() => {
    if (!timeline) return [];
    const months = newestFirst ? timeline.months : [...timeline.months].reverse();
    const total = months.reduce((n, m) => n + m.count, 0) + timeline.undated;
    if (total === 0) return [];
    const out: Segment[] = [];
    let at = 0;
    for (const m of months) {
      out.push({ key: m.month, year: m.month.slice(0, 4), top: at / total, height: m.count / total });
      at += m.count;
    }
    if (timeline.undated > 0) out.push({ key: "none", year: "none", top: at / total, height: timeline.undated / total });
    return out;
  }, [timeline, newestFirst]);

  // Year labels, the years holding the most photos first, each where it has room from those
  // already placed: a large year is never left unlabelled beside a near-empty one.
  const labels = useMemo(() => {
    const years = new Map<string, { top: number; size: number }>();
    for (const s of segments) {
      const y = years.get(s.year);
      if (y) y.size += s.height; else years.set(s.year, { top: s.top, size: s.height });
    }
    const placed: { key: string; text: string; top: number }[] = [];
    for (const [year, y] of [...years].sort((a, b) => b[1].size - a[1].size)) {
      const at = y.top * height;
      if (at > height - LABEL_SPACE / 2) continue;
      if (placed.some((l) => Math.abs(l.top * height - at) < LABEL_SPACE)) continue;
      placed.push({ key: year, text: dateLabel(year), top: y.top });
    }
    return placed.sort((a, b) => a.top - b.top);
  }, [segments, height]);

  const at = (clientY: number): Segment | null => {
    const box = track.current?.getBoundingClientRect();
    if (!box || !segments.length) return null;
    const f = Math.min(0.9999, Math.max(0, (clientY - box.top) / box.height));
    return segments.find((s) => f < s.top + s.height) ?? segments[segments.length - 1];
  };
  const down = (e: ReactPointerEvent) => {
    dragging.current = true;
    track.current?.setPointerCapture(e.pointerId);
    setHover(at(e.clientY));
  };
  const move = (e: ReactPointerEvent) => setHover(at(e.clientY));
  const up = (e: ReactPointerEvent) => {
    if (!dragging.current) return;
    dragging.current = false;
    const s = at(e.clientY);
    if (s) onJump(s.key);
  };
  const shown = segments.find((s) => current.includes(s.key));

  return (
    <nav className="scrubber" aria-label="Jump to a date">
      <div className="scrubber-track" ref={track} onPointerDown={down} onPointerMove={move} onPointerUp={up}
           onPointerLeave={() => { if (!dragging.current) setHover(null); }}>
        {shown && <span className="scrubber-marker" style={{ top: `${shown.top * 100}%` }} aria-hidden="true" />}
        {labels.map((l) => (
          <button key={l.key} type="button" className="scrubber-year" style={{ top: `${l.top * 100}%` }}
                  aria-label={`Go to ${dateLabel(l.key)}`} onPointerDown={(e) => e.stopPropagation()}
                  onClick={() => onJump(l.key)}>{l.text}</button>
        ))}
        {hover && (
          <span className="scrubber-hover" style={{ top: `${(hover.top + hover.height / 2) * 100}%` }} aria-hidden="true">
            {dateLabel(hover.key)}
          </span>
        )}
      </div>
    </nav>
  );
}
