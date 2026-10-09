import { useEffect, useState, type MouseEvent } from "react";
import { api, savedMatchMinimum, type LookInto, type PlaceView, type Places, type Status } from "../api";
import { count } from "../format";
import { follow } from "../nav";
import { VersionTag } from "./VersionTag";

// What the sidebar marks as current: a place, or Logs or Stats.
export interface SidebarCurrent { place?: PlaceView | null; page?: "logs" | "stats" }

// The Library page's filters, shown in Look into: on or off, the count in the place shown
// under the other filters, and why a filter does not apply to that place (null: it does).
export interface SidebarFilters {
  on: Record<LookInto, boolean>;
  counts: Partial<Record<LookInto, number>>;
  why: Record<LookInto, string | null>;
  onToggle: (key: LookInto) => void;
}

const PLACES: { view: PlaceView; label: string }[] = [
  { view: "unorganized", label: "Not organized" },
  { view: "organized", label: "Library" },
  { view: "review", label: "Needs review" },
  { view: "rejects", label: "Rejects" },
];
// Where each filter opens from Logs and Stats: Library with only it on; Review later is
// Needs review's.
const LOOK: { key: LookInto; label: string; href: string }[] = [
  { key: "similar", label: "Has similar photos", href: "/?view=organized&similar=1" },
  { key: "suspicious", label: "Suspicious dates", href: "/?view=organized&suspicious=1" },
  { key: "undated", label: "No capture date", href: "/?view=organized&undated=1" },
  { key: "small", label: "Small images", href: "/?view=organized&reason=small" },
  { key: "later", label: "Review later", href: "/?view=review&reason=later" },
];

const plainClick = (e: MouseEvent) => e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;

// The navigation sidebar (webui-spec 2, the page frame), on every page: the places with
// how many photos each holds, the Look into filters, then Logs and Stats, and the build at
// the foot. Places and pages are real links, so a middle click opens a new tab. On the
// Library page a place keeps the search and filters (`onPlace`), and Look into holds the
// gallery's filters (`filters`): toggles that combine within the place shown. Elsewhere
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
      <button key={l.key} type="button" className="sidebar-item" aria-pressed={f.on[l.key]}
              aria-disabled={why ? true : undefined} title={why ?? undefined}
              onClick={() => { if (why) return; onNavigate?.(); f.onToggle(l.key); }}>
        {content(l.label, why ? undefined : f.counts[l.key])}
      </button>
    );
  };
  return (
    <nav id="sidebar" className="sidebar" aria-label="Main">
      {PLACES.map((p) => link(`/?view=${p.view}`, p.label, current.place === p.view, counts?.places[p.view], p.view))}
      <h2 className="sidebar-heading" id="look-into">Look into</h2>
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
