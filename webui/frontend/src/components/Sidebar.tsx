import { Fragment, useEffect, useState } from "react";
import { api, savedMatchMinimum, type PlaceView, type Places, type Status } from "../api";
import { count } from "../format";
import { follow } from "../nav";
import { VersionTag } from "./VersionTag";
import { LibraryStatus } from "./LibraryStatus";

export interface SidebarCurrent { place?: PlaceView | null; sourceFolders?: boolean; page?: "logs" | "stats" }
const PLACES: { view: PlaceView; label: string; href: string }[] = [
  { view: "unorganized", label: "Not organized", href: "/?view=unorganized" },
  { view: "organized", label: "Library", href: "/?view=organized" },
  { view: "similar", label: "Similar photos", href: "/?view=organized&similar=1" },
  { view: "rejects", label: "Rejects", href: "/?view=rejects" },
];

// Places have whole-library counts. Warning links open their complete affected scope.
// Notes under a place put their count on the right, aligned with the places' counts.
export function Sidebar({ current, version, matchMin, refresh, onNavigate }: {
  current: SidebarCurrent; version: Status["version"]; matchMin?: number;
  refresh?: unknown; onNavigate?: () => void;
}) {
  const [counts, setCounts] = useState<Places | null>(null);
  const [changed, setChanged] = useState(0);
  useEffect(() => {
    const bump = () => setChanged(n => n + 1);
    window.addEventListener("ns-review-changed", bump);
    return () => window.removeEventListener("ns-review-changed", bump);
  }, []);
  useEffect(() => {
    let live = true;
    api.places(matchMin ?? savedMatchMinimum()).then(p => live && setCounts(p), () => live && setCounts(null));
    return () => { live = false; };
  }, [matchMin, refresh, changed]);
  const go: React.MouseEventHandler<HTMLAnchorElement> = e => { onNavigate?.(); follow(e); };
  return <nav id="sidebar" className="sidebar" aria-label="Main">
    {PLACES.map(p => <Fragment key={p.view}>
      <a href={p.href} aria-current={current.place === p.view ? "page" : undefined} onClick={go}>
        <span className="sidebar-label">{p.label}</span><span className="sidebar-count">{counts ? count(counts.places[p.view]) : "—"}</span>
      </a>
      {p.view === "unorganized" && <>
        <a href="/?view=unorganized&tree=1" className="sidebar-sub" aria-current={current.sourceFolders ? "page" : undefined} onClick={go}>Source folders</a>
        {!!counts?.warnings.attention && <a href="/?view=unorganized&reason=attention" className="sidebar-note warning-text" onClick={go}
          aria-label={`${count(counts.warnings.attention)} need attention`}><span className="sidebar-label">Need attention</span><span className="sidebar-count">{count(counts.warnings.attention)}</span></a>}
      </>}
      {p.view === "organized" && !!counts?.places.review && <a href="/?view=review" className="sidebar-note" onClick={go}
        aria-label={`${count(counts.places.review)} to review`}><span className="sidebar-label">To review</span><span className="sidebar-count">{count(counts.places.review)}</span></a>}
      {p.view === "organized" && !!counts?.originals && <a href="/?view=source&tree=1" className="sidebar-note" onClick={go}
        aria-label={`${count(counts.originals)} originals in source`}
        title="Their originals are still in the source. Source folders › Still in source lists them; Move this folder… removes them."><span className="sidebar-label">Originals in source</span><span className="sidebar-count">{count(counts.originals)}</span></a>}
    </Fragment>)}
    <div className="sidebar-activity">
      <h2 className="sidebar-heading">Activity</h2>
      <a href="/logs" aria-current={current.page === "logs" ? "page" : undefined} onClick={go}>Logs</a>
      <a href="/stats" aria-current={current.page === "stats" ? "page" : undefined} onClick={go}>Stats</a>
      <LibraryStatus refresh={refresh} onNavigate={onNavigate} />
      <div className="sidebar-foot"><VersionTag version={version} /></div>
    </div>
  </nav>;
}
