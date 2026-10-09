import { useEffect, useState, type MouseEvent } from "react";
import { api, savedMatchMinimum, type LookInto, type PlaceView, type Places, type Status } from "../api";
import { count } from "../format";
import { follow } from "../nav";
import { VersionTag } from "./VersionTag";

// What the sidebar marks as current: a place, a Look into shortcut, or Logs or Stats.
export interface SidebarCurrent { place?: PlaceView | null; look?: LookInto | null; page?: "logs" | "stats" }

const PLACES: { view: PlaceView; label: string }[] = [
  { view: "unorganized", label: "Not organized" },
  { view: "organized", label: "Library" },
  { view: "review", label: "Needs review" },
  { view: "rejects", label: "Rejects" },
];
// Library with only that filter on. They carry the filter chips' labels: the same filter.
const LOOK: { key: LookInto; label: string; query: string }[] = [
  { key: "similar", label: "Has similar photos", query: "similar=1" },
  { key: "suspicious", label: "Suspicious dates", query: "suspicious=1" },
  { key: "undated", label: "No capture date", query: "undated=1" },
  { key: "small", label: "Small images", query: "reason=small" },
];

const plainClick = (e: MouseEvent) => e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;

// The navigation sidebar (webui-spec 2, the page frame), on every page: the places with
// their whole counts, the Look into shortcuts, then Logs and Stats, and the build at the
// foot. Real links, so a middle click opens a new tab. Each count is what its link
// shows: on the Library page a place keeps the search and filters (`onPlace`), so it
// counts under them (`placeCounts`); elsewhere a place opens whole; a Look into link
// opens Library with only its filter.
export function Sidebar({ current, version, matchMin, refresh, placeCounts, onPlace, onNavigate }: {
  current: SidebarCurrent;
  version: Status["version"];
  matchMin?: number;
  refresh?: unknown;
  placeCounts?: Record<PlaceView, number>;
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
  const link = (href: string, label: string, on: boolean, n: number | undefined, view?: PlaceView) => (
    <a key={href} href={href} aria-current={on ? "page" : undefined} onClick={(e) => go(e, view)}>
      <span>{label}</span>{" "}
      {n !== undefined && <span className="sidebar-count">{count(n)}</span>}
    </a>
  );
  return (
    <nav id="sidebar" className="sidebar" aria-label="Main">
      {PLACES.map((p) => link(`/?view=${p.view}`, p.label, current.place === p.view, (placeCounts ?? counts?.places)?.[p.view], p.view))}
      <h2 className="sidebar-heading">Look into</h2>
      {LOOK.map((l) => link(`/?view=organized&${l.query}`, l.label, current.look === l.key, counts?.look_into[l.key]))}
      <h2 className="sidebar-heading">Activity</h2>
      {link("/logs", "Logs", current.page === "logs", undefined)}
      {link("/stats", "Stats", current.page === "stats", undefined)}
      <div className="sidebar-foot"><VersionTag version={version} /></div>
    </nav>
  );
}
