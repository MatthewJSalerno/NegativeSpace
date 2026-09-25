import { useState } from "react";
import { count, plural } from "../format";

export const PAGE_SIZES = [60, 120, 240];

const cap = (w: string) => w[0].toUpperCase() + w.slice(1);

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

// Positions in a large list: first/last, numbered pages, a go-to box, and a size. The
// gallery scrolls on through pages (`continuous`: the size is how many load at a time);
// the log shows one page at a time. Either way a page number is a place a refresh returns to.
export function Pager({ page, pages, total, pageSize, onPage, onPageSize, sizes = PAGE_SIZES, noun = "photo", nouns, continuous }: {
  page: number;
  pages: number;
  total: number;
  pageSize: number;
  onPage: (p: number) => void;
  onPageSize: (n: number) => void;
  sizes?: number[];
  noun?: string;
  nouns?: string;
  // The gallery scrolls on through pages: the size is how many load at a time.
  continuous?: boolean;
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
      <select value={pageSize} onChange={(e) => onPageSize(Number(e.target.value))}
              aria-label={continuous ? `${cap(nouns ?? `${noun}s`)} loaded at a time` : `${cap(nouns ?? `${noun}s`)} per page`}>
        {sizes.map((n) => <option key={n} value={n}>{continuous ? `Load ${n} at a time` : `${n} per page`}</option>)}
      </select>
      <span className="muted">{plural(total, noun, nouns)}</span>
    </nav>
  );
}
