import { Fragment, useEffect, useState, type MouseEvent } from "react";
import { api, savedMatchMinimum, type LookInto, type PlaceView, type Places, type Status } from "../api";
import { count } from "../format";
import { follow } from "../nav";
import { VersionTag } from "./VersionTag";

// What the sidebar marks as current: a place, Source folders, or Logs or Stats.
export interface SidebarCurrent { place?: PlaceView | null; sourceFolders?: boolean; page?: "logs" | "stats" }

// The Library page's filters, shown in Look into: on or off, the count in the place shown
// under the other filters, and why a filter does not apply to that place (null: it does).
export interface SidebarFilters {
  on: Record<LookInto, boolean>;
  counts: Partial<Record<LookInto, number>>;
  why: Record<LookInto, string | null>;
  onToggle: (key: LookInto) => void;
  pinned: LookInto[];
  onPin: (key: LookInto) => void;
  onClear?: () => void;
}

const PLACES: { view: PlaceView; label: string }[] = [
  { view: "unorganized", label: "Not organized" },
  { view: "organized", label: "Library" },
  { view: "review", label: "Needs review" },
  { view: "rejects", label: "Rejects" },
];
// Where each filter opens from Logs and Stats: Library with only it on; Review later is
// Needs review's. Source attention has its own navigation entry under Not organized.
const LOOK: { key: LookInto; label: string; href: string }[] = [
  { key: "similar", label: "Has similar photos", href: "/?view=organized&similar=1" },
  { key: "suspicious", label: "Suspicious dates", href: "/?view=organized&suspicious=1" },
  { key: "undated", label: "No capture date", href: "/?view=organized&undated=1" },
  { key: "small", label: "Small images", href: "/?view=organized&reason=small" },
  { key: "issues", label: "Files needing verification", href: "/?view=organized&reason=issues" },
  { key: "later", label: "Review later", href: "/?view=review&reason=later" },
];

const plainClick = (e: MouseEvent) => e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;

// The navigation sidebar (webui-spec 2, the page frame), on every page: the places with
// how many photos each holds, the Look into filters, then Logs and Stats, and the build at
// the foot. Places and pages are real links, so a middle click opens a new tab. On the
// Library page a place keeps the search and filters (`onPlace`), and Look into holds the
// gallery's filters (`filters`): click to browse, pin to retain while choosing another. Elsewhere
// a Look into item is a link to Library with only that filter on.
export function Sidebar({ current, version, matchMin, refresh, filters, onPlace, onNavigate }: {
  current: SidebarCurrent;
  version: Status["version"];
  matchMin?: number;
  refresh?: unknown;
  filters?: SidebarFilters;
  onPlace?: (view: PlaceView) => void;
  onNavigate?: () => void;
}) {
  const [counts, setCounts] = useState<Places | null>(null);
  const [changed, setChanged] = useState(0);
  useEffect(() => {
    const bump = () => setChanged((n) => n + 1);
    window.addEventListener("ns-review-changed", bump);
    return () => window.removeEventListener("ns-review-changed", bump);
  }, []);
  useEffect(() => {
    let live = true;
    api.places(matchMin ?? savedMatchMinimum()).then((p) => live && setCounts(p), () => live && setCounts(null));
    return () => { live = false; };
  }, [matchMin, refresh, changed]);

  const go = (e: MouseEvent<HTMLAnchorElement>, view?: PlaceView) => {
    onNavigate?.();
    if (view && onPlace && plainClick(e)) { e.preventDefault(); onPlace(view); }
    else follow(e);
  };
  const attentionCurrent = current.place === "unorganized" && filters?.on.attention;
  const content = (label: string, n: number | undefined) => <>
    <span>{label}</span>{" "}
    {n !== undefined && <span className="sidebar-count">{count(n)}</span>}
  </>;
  const link = (href: string, label: string, on: boolean, n: number | undefined, view?: PlaceView) => (
    <a key={href} href={href} aria-current={on ? "page" : undefined} onClick={(e) => go(e, view)}>{content(label, n)}</a>
  );
  // A filter that does not apply here stays in its row, dimmed, and says why on hover
  // and to assistive technology, so the sidebar never shifts between places.
  const toggle = (l: (typeof LOOK)[number], f: SidebarFilters) => {
    const why = f.why[l.key];
    return (
      <div key={l.key} className="sidebar-filter-row">
      <button type="button" className="sidebar-item" aria-pressed={f.on[l.key]}
              aria-disabled={why ? true : undefined} title={why ?? undefined}
              onClick={() => { if (why) return; onNavigate?.(); f.onToggle(l.key); }}>
        {content(l.label, why ? undefined : f.counts[l.key])}
      </button>
      <button type="button" className="filter-pin" aria-pressed={f.pinned.includes(l.key)}
              aria-label={`${f.pinned.includes(l.key) ? "Unpin" : "Pin"} ${l.label}`}
              aria-disabled={why && !f.pinned.includes(l.key) ? true : undefined}
              title={f.pinned.includes(l.key) ? why ? `Pinned, unavailable here: ${why} Click to unpin.` : !f.on[l.key] ? "Pinned, not applied to this link. Click the filter to apply; click the pin to unpin." : "Pinned: keep this filter while browsing others. Click to unpin and turn off this filter."
                : why ?? "Pin this filter to keep it while browsing others."}
              onClick={() => { if (!why || f.pinned.includes(l.key)) f.onPin(l.key); }}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M8 3h8M9 3v6l-3 4v2h12v-2l-3-4V3M12 15v6" />
        </svg>
      </button>
      </div>
    );
  };
  return (
    <nav id="sidebar" className="sidebar" aria-label="Main">
      {PLACES.map((p) => <Fragment key={p.view}>
        {link(`/?view=${p.view}`, p.label, current.place === p.view && !attentionCurrent, counts?.places[p.view], p.view)}
        {/* The source's folders, under the place whose photos are still in them. */}
        {p.view === "unorganized" && <a href="/?view=unorganized&tree=1" className="sidebar-sub"
           aria-current={current.sourceFolders ? "page" : undefined} onClick={(e) => go(e)}><span>Source folders</span></a>}
        {p.view === "unorganized" && <a href="/?view=unorganized&reason=attention" className="sidebar-sub"
           aria-current={attentionCurrent ? "page" : undefined} onClick={(e) => go(e)}>
          {content("Needs attention", counts?.look_into.attention)}
        </a>}
      </Fragment>)}
      <div className="sidebar-filter-heading">
        <h2 className="sidebar-heading" id="look-into">Look into</h2>
        <button type="button" className="link" style={{ visibility: filters?.onClear ? "visible" : "hidden" }}
                onClick={() => { filters?.onClear?.(); onNavigate?.(); }}>Clear all filters</button>
      </div>
      <div className="sidebar-group" role="group" aria-labelledby="look-into">
        {LOOK.map((l) => filters ? toggle(l, filters) : link(l.href, l.label, false, counts?.look_into[l.key]))}
      </div>
      <h2 className="sidebar-heading">Activity</h2>
      {link("/logs", "Logs", current.page === "logs", undefined)}
      {link("/stats", "Stats", current.page === "stats", undefined)}
      <div className="sidebar-foot"><VersionTag version={version} /></div>
    </nav>
  );
}
