import { useEffect, useState } from "react";
import type { Sort, Timeline } from "../api";
import { count, plural } from "../format";

export const PAGE_SIZES = [60, 120, 240];

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
  "October", "November", "December"];

// Page numbers to show: the first, the last, and two either side of the current
// page, with gaps marked - "1 … 48 49 [50] 51 52 … 2,500".
function pageList(page: number, pages: number): (number | "gap")[] {
  const wanted = new Set([1, pages, page - 2, page - 1, page, page + 1, page + 2].filter((p) => p >= 1 && p <= pages));
  const sorted = [...wanted].sort((a, b) => a - b);
  const out: (number | "gap")[] = [];
  sorted.forEach((p, i) => {
    if (i > 0 && p - sorted[i - 1] > 1) out.push("gap");
    out.push(p);
  });
  return out;
}

// Paging for a large library: first/last, numbered pages, a go-to box, and a page
// size. Pages rather than endless scrolling, because selection is defined per page
// (webui-spec 2) and a page number is a place a refresh can return to.
export function Pager({ page, pages, total, pageSize, onPage, onPageSize, sizes = PAGE_SIZES, noun = "photo", nouns }: {
  page: number;
  pages: number;
  total: number;
  pageSize: number;
  onPage: (p: number) => void;
  onPageSize: (n: number) => void;
  sizes?: number[];
  noun?: string;
  nouns?: string;
}) {
  const [goto, setGoto] = useState("");
  const go = () => {
    const n = Number(goto.replace(/[^0-9]/g, ""));
    if (n >= 1) onPage(Math.min(n, pages));
    setGoto("");
  };
  return (
    <nav className="pager" aria-label="Pages">
      <button onClick={() => onPage(1)} disabled={page <= 1} aria-label="First page" title="First page">«</button>
      <button onClick={() => onPage(page - 1)} disabled={page <= 1} aria-label="Previous page" title="Previous page">‹</button>
      {pageList(page, pages).map((p, i) => p === "gap"
        ? <span key={`gap-${i}`} className="muted" aria-hidden="true">…</span>
        : <button key={p} className={p === page ? "current" : ""} aria-current={p === page ? "page" : undefined}
                  onClick={() => onPage(p)}>{count(p)}</button>)}
      <button onClick={() => onPage(page + 1)} disabled={page >= pages} aria-label="Next page" title="Next page">›</button>
      <button onClick={() => onPage(pages)} disabled={page >= pages} aria-label="Last page" title="Last page">»</button>
      <span className="pager-goto">
        <input value={goto} onChange={(e) => setGoto(e.target.value)} onKeyDown={(e) => e.key === "Enter" && go()}
               placeholder="Page" aria-label="Go to page" inputMode="numeric" />
        <button onClick={go}>Go</button>
      </span>
      <select value={pageSize} onChange={(e) => onPageSize(Number(e.target.value))} aria-label={`${(nouns ?? `${noun}s`)[0].toUpperCase()}${(nouns ?? `${noun}s`).slice(1)} per page`}>
        {sizes.map((n) => <option key={n} value={n}>{n} per page</option>)}
      </select>
      <span className="muted">{plural(total, noun, nouns)}</span>
    </nav>
  );
}

// Jump to a month in a date-sorted gallery. Each month's first photo sits at the
// number of photos sorted before it, which gives its page directly.
export function JumpToDate({ timeline, sort, pageSize, onPage }: {
  timeline: Timeline | null;
  sort: Sort;
  pageSize: number;
  onPage: (p: number) => void;
}) {
  const [value, setValue] = useState("");
  useEffect(() => setValue(""), [sort, timeline]);
  if (!timeline || (sort !== "newest" && sort !== "oldest") || timeline.months.length === 0) return null;
  const months = sort === "newest" ? timeline.months : [...timeline.months].reverse();
  const offsets = new Map<string, number>();
  let before = 0;
  for (const m of months) {
    offsets.set(m.month, before);
    before += m.count;
  }
  const years = [...new Set(months.map((m) => m.month.slice(0, 4)))];
  const jump = (month: string) => {
    setValue(month);
    const offset = month === "undated" ? before : offsets.get(month);
    if (offset != null) onPage(Math.floor(offset / pageSize) + 1);
  };
  return (
    <label className="jump">
      <span>Jump to</span>
      <select value={value} onChange={(e) => e.target.value && jump(e.target.value)} aria-label="Jump to a month">
        <option value="">Month…</option>
        {years.map((y) => (
          <optgroup key={y} label={y}>
            {months.filter((m) => m.month.startsWith(y)).map((m) => (
              <option key={m.month} value={m.month}>
                {MONTHS[Number(m.month.slice(5, 7)) - 1]} {y} ({count(m.count)})
              </option>
            ))}
          </optgroup>
        ))}
        {timeline.undated > 0 && <option value="undated">No date ({count(timeline.undated)})</option>}
      </select>
    </label>
  );
}
