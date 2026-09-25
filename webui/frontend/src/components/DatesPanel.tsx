import { useEffect, useMemo, useRef, useState } from "react";
import type { Timeline } from "../api";
import { count } from "../format";

export const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
  "October", "November", "December"];

// Readable names for the date filter: "June 2023", "2019", "No date".
export function dateLabel(key: string): string {
  if (key === "none") return "No date";
  if (key.length === 4) return key;
  return `${MONTH_NAMES[Number(key.slice(5, 7)) - 1]} ${key.slice(0, 4)}`;
}

// The date tree (webui-spec 2): years with their months, with counts for the current
// view and search. Clicking a name jumps the gallery there; the boxes under "Show only"
// narrow it to the ticked years and months. None ticked shows every date.
export function DatesPanel({ timeline, dates, current, oldestFirst, onDates, onJump }: {
  timeline: Timeline | null;
  dates: string[];
  // Every month with a photo on screen ("2023-06").
  current: string[];
  // The gallery's date order: oldest first lists the oldest year and month first.
  oldestFirst: boolean;
  onDates: (dates: string[]) => void;
  onJump: (key: string) => void;
}) {
  const years = useMemo(() => {
    const out = new Map<string, { month: string; count: number }[]>();
    const months = timeline?.months ?? [];           // newest first, as the API sends them
    for (const m of oldestFirst ? [...months].reverse() : months) {
      const y = m.month.slice(0, 4);
      out.set(y, [...(out.get(y) ?? []), m]);
    }
    return [...out.entries()];
  }, [timeline, oldestFirst]);
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const seeded = useRef(false);
  // Every year starts unfolded; folding one is kept while the page is open.
  useEffect(() => {
    if (!seeded.current && years.length) { seeded.current = true; setOpen(new Set(years.map(([y]) => y))); }
  }, [years]);

  // Keep the highlighted months in sight in a long tree, without moving the page.
  const panel = useRef<HTMLElement>(null);
  const currentKey = current.join();
  useEffect(() => {
    panel.current?.querySelector(".dates-row.current")?.scrollIntoView({ block: "nearest" });
  }, [currentKey]);

  if (!timeline) return null;
  const has = (key: string) => dates.includes(key);
  const monthOn = (month: string) => has(month) || has(month.slice(0, 4));

  const toggleYear = (year: string, months: { month: string }[]) => {
    const rest = dates.filter((d) => d !== year && !d.startsWith(`${year}-`));
    const all = has(year) || months.every((m) => has(m.month));
    onDates(all ? rest : [...rest, year]);
  };
  const toggleMonth = (month: string, months: { month: string }[]) => {
    const year = month.slice(0, 4);
    if (has(year)) {
      // Unticking one month of a ticked year: the year's other months stay ticked.
      onDates([...dates.filter((d) => d !== year), ...months.map((m) => m.month).filter((m) => m !== month)]);
    } else if (has(month)) {
      onDates(dates.filter((d) => d !== month));
    } else {
      const next = [...dates, month];
      // Every month ticked is the year ticked.
      onDates(months.every((m) => next.includes(m.month)) ? [...next.filter((d) => !d.startsWith(`${year}-`)), year] : next);
    }
  };
  const toggleNone = () => onDates(has("none") ? dates.filter((d) => d !== "none") : [...dates, "none"]);

  return (
    <nav className="dates-panel" aria-label="Dates" ref={panel}>
      <div className="dates-head">
        <h2>Dates</h2>
        <span className="dates-show-only" title="Check years or months to show only those. Uncheck them all to show everything.">
          Show only <span aria-hidden="true">ⓘ</span>
        </span>
      </div>
      <ul className="dates-tree">
        {years.map(([year, months]) => {
          const ticked = months.filter((m) => monthOn(m.month)).length;
          const isOpen = open.has(year);
          const total = months.reduce((n, m) => n + m.count, 0);
          return (
            <li key={year}>
              <div className={`dates-row ${current.some((m) => m.startsWith(year)) ? "current" : ""}`}>
                <input type="checkbox" aria-label={`Show only ${year}`} checked={ticked === months.length}
                       ref={(el) => { if (el) el.indeterminate = ticked > 0 && ticked < months.length; }}
                       onChange={() => toggleYear(year, months)} />
                <button className="dates-caret" aria-label={isOpen ? `Fold ${year}` : `Unfold ${year}`} aria-expanded={isOpen}
                        onClick={() => setOpen((cur) => { const n = new Set(cur); if (n.has(year)) n.delete(year); else n.add(year); return n; })}>
                  {isOpen ? "▾" : "▸"}
                </button>
                <button className="dates-name" onClick={() => onJump(year)} title={`Go to ${year}`}>{year}</button>
                <span className="dates-count">{count(total)}</span>
              </div>
              {isOpen && (
                <ul>
                  {months.map((m) => (
                    <li key={m.month} className={`dates-row month ${current.includes(m.month) ? "current" : ""}`}>
                      <input type="checkbox" aria-label={`Show only ${dateLabel(m.month)}`} checked={monthOn(m.month)}
                             onChange={() => toggleMonth(m.month, months)} />
                      <button className="dates-name" onClick={() => onJump(m.month)} title={`Go to ${dateLabel(m.month)}`}>
                        {MONTH_NAMES[Number(m.month.slice(5, 7)) - 1]}
                      </button>
                      <span className="dates-count">{count(m.count)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
        {timeline.undated > 0 && (
          <li className="dates-row">
            <input type="checkbox" aria-label="Show only photos with no date" checked={has("none")} onChange={toggleNone} />
            <span className="dates-caret" />
            <button className="dates-name" onClick={() => onJump("none")}>No date</button>
            <span className="dates-count">{count(timeline.undated)}</span>
          </li>
        )}
      </ul>
      <p className="dates-foot muted">
        {dates.length === 0 ? "Showing all dates" : <>Showing only {dates.map(dateLabel).join(", ")} · <button className="link" onClick={() => onDates([])}>Show all</button></>}
      </p>
    </nav>
  );
}

// The page a year, month or "none" starts on in a date-sorted gallery: each one's first
// photo sits after every photo sorted before it. `timeline` is the filtered one.
export function datePage(timeline: Timeline, newestFirst: boolean, pageSize: number, key: string): number | null {
  const months = newestFirst ? timeline.months : [...timeline.months].reverse();
  let before = 0;
  for (const m of months) {
    if (m.month === key || m.month.startsWith(`${key}-`)) return Math.floor(before / pageSize) + 1;
    before += m.count;
  }
  return key === "none" && timeline.undated > 0 ? Math.floor(before / pageSize) + 1 : null;
}
