import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, type MatchPage, type MatchPhoto, type Status } from "../api";
import { bytes, plural } from "../format";
import { follow, navigate, photoUrl, useHeaderHeight, useNavigation } from "../nav";
import { useDismissedRun, useJobFeed } from "../jobs";
import { FinishedBanner, JobDrawer } from "./JobDrawer";
import { Logo } from "./Logo";
import { Pager } from "./Pager";
import { StatsLink } from "./StatsPage";
import { Thumb } from "./Thumb";
import { VersionTag } from "./VersionTag";
import { MatchReviewDialog } from "./MatchReviewDialog";
import { MatchDiagnosticsPanel } from "./MatchDiagnosticsPanel";

function read() {
  const p = new URLSearchParams(location.search);
  const positive = (key: string) => Math.max(1, Math.floor(Number(p.get(key)) || 1));
  return {
    threshold: Math.min(100, Math.max(90, Number(p.get("threshold") ?? 90) || 90)),
    sort: ["matches", "newest", "oldest", "name", "largest"].includes(p.get("sort") || "") ? p.get("sort")! : "matches",
    q: p.get("q") || "", page: positive("page"),
    photo: p.has("photo") ? positive("photo") : null, match_page: positive("match_page"),
    page_size: [30, 60].includes(Number(p.get("page_size"))) ? Number(p.get("page_size")) : 30,
  };
}

function savedScroll() {
  try { return Number(sessionStorage.getItem(`similar-scroll:${location.search}`)) || 0; }
  catch { return 0; }
}

export function SimilarPage({ status, onOpenSettings }: { status: Status; onOpenSettings: () => void }) {
  const [filters, setFilters] = useState(read);
  const [queue, setQueue] = useState<MatchPage | null>(null);
  const [matches, setMatches] = useState<MatchPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [reviewPair, setReviewPair] = useState<[number, number] | null>(null);
  const [reviewsChanged, setReviewsChanged] = useState(0);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const restoreScroll = useRef<number | null>(savedScroll());
  const header = useRef<HTMLElement>(null);
  useHeaderHeight(header);
  useNavigation(useCallback(() => { restoreScroll.current = savedScroll(); setFilters(read()); }, []));
  useLayoutEffect(() => {
    if (!loading && restoreScroll.current !== null) {
      window.scrollTo(0, restoreScroll.current);
      restoreScroll.current = null;
    }
  }, [loading]);
  useEffect(() => {
    if (loading) return;
    const query = location.search;
    const key = `similar-scroll:${query}`;
    const save = () => {
      // Navigation can change the document height before this listener is removed.
      if (location.pathname !== "/similar" || location.search !== query) return;
      try { sessionStorage.setItem(key, String(window.scrollY)); } catch { /* Storage is optional. */ }
    };
    window.addEventListener("scroll", save, { passive: true });
    return () => window.removeEventListener("scroll", save);
  }, [filters, loading]);
  const { jobs, connection } = useJobFeed();
  const [dismissedId, dismissRun] = useDismissedRun();
  const jobKey = `${jobs.last?.id}:${jobs.last?.status}:${connection}`;
  const update = (change: Partial<typeof filters>, push = false) => {
    const next = { ...filters, ...change };
    const p = new URLSearchParams();
    Object.entries(next).forEach(([key, value]) => { if (value !== null) p.set(key, String(value)); });
    restoreScroll.current = 0;
    if (push) navigate(`/similar?${p}`);
    else { history.replaceState(null, "", `/similar?${p}`); setFilters(next); }
  };
  const reload = () => { restoreScroll.current = window.scrollY; setRefresh((n) => n + 1); };
  useEffect(() => {
    let live = true;
    if (restoreScroll.current === null) restoreScroll.current = window.scrollY;
    setError(null); setLoading(true);
    const p = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => { if (value !== null) p.set(key, String(value)); });
    const detail = new URLSearchParams(p);
    detail.set("page", String(filters.match_page));
    Promise.all([api.matches(p), filters.photo ? api.matches(detail, filters.photo) : Promise.resolve(null)])
      .then(([q, m]) => {
        if (!live) return;
        const last = Math.max(1, Math.ceil(q.total / filters.page_size));
        const matchLast = Math.max(1, Math.ceil((m?.total ?? 0) / filters.page_size));
        if (filters.page > last || filters.match_page > matchLast) {
          update({ page: Math.min(filters.page, last), match_page: Math.min(filters.match_page, matchLast) });
          return;
        }
        setQueue(q); setMatches(m); setLoading(false);
      }, (e) => {
        if (live) { setQueue(null); setMatches(null); setLoading(false); setError(e instanceof Error ? e.message : "Matches could not be loaded."); }
      });
    return () => { live = false; };
  }, [filters, refresh, jobKey]);

  const picture = (photo: MatchPhoto, detail = false) => <article className="match-card" key={photo.id}>
    {detail ? <a className="match-image" href={photoUrl(photo.id)} onClick={follow} aria-label={`Inspect ${photo.filename}`}>
      <Thumb id={photo.id} alt={photo.filename} size="preview" />
    </a> : <button className="match-image" onClick={() => update({ photo: photo.id, match_page: 1 }, true)} aria-label={`Compare ${photo.filename}`}>
      <Thumb id={photo.id} alt={photo.filename} />
    </button>}
    <div className="match-caption"><strong>{photo.filename}</strong>
      <span>{photo.width && photo.height ? `${photo.width} × ${photo.height}` : "Dimensions unknown"} · {bytes(photo.file_size)}</span>
      {detail && matches?.largest_pixels != null && photo.width && photo.height && photo.width * photo.height === matches.largest_pixels
        ? <span className="badge">Largest dimensions</span> : null}
      {photo.matches != null && <span>{plural(photo.matches, "match", "matches")}</span>}
      {photo.score != null && <span>{photo.score}% visual match</span>}
      {detail && <a href={photoUrl(photo.id)} onClick={follow}>Photo details and history</a>}
      {detail && matches?.reference && photo.id !== matches.reference.id && <button
        onClick={() => setReviewPair([matches.reference!.id, photo.id])}>Review side by side</button>}
    </div>
  </article>;
  const pager = (data: MatchPage, detail = false) => <Pager page={detail ? filters.match_page : filters.page}
    pages={Math.max(1, Math.ceil(data.total / filters.page_size))} total={data.total} pageSize={filters.page_size} sizes={[30, 60]}
    onPage={(n) => update(detail ? { match_page: n } : { page: n })}
    onPageSize={(n) => update({ page_size: n, page: 1, match_page: 1 })} />;

  return <div className="app">
    <header className="toolbar" ref={header}><div className="toolbar-row">
      <h1 className="brand"><Logo />NegativeSpace</h1>
      <nav className="pages" aria-label="Pages">
        <a className="button-link" href="/" onClick={follow}>Library</a>
        <a className="button-link" href="/logs" onClick={follow}>Logs</a>
        <a className="button-link active" href="/similar" onClick={follow} aria-current="page">Similar</a>
      </nav>
      <div className="toolbar-actions"><VersionTag version={status.version} /><StatsLink />
        <button className="icon" onClick={onOpenSettings} aria-label="Settings" title="Settings">⚙</button>
      </div>
    </div><JobDrawer jobs={jobs} connection={connection} />
      <FinishedBanner jobs={jobs} dismissedId={dismissedId} onDismiss={dismissRun} />
    </header>
    <main id="main-content" tabIndex={-1} className="similar-page">
      <h2>Photos with visual matches</h2>
      <p className="muted">Review visually similar photos at the destination. Index your photos, then Copy or Move them before reviewing matches.</p>
      <p className="muted">Destination availability is recorded from the last observation.</p>
      <p className="muted">The percentage measures hash similarity, not confidence. A 100% score does not mean identical pictures.</p>
      <details onToggle={(e) => setDiagnosticsOpen(e.currentTarget.open)}><summary>Validation and performance</summary>
        {diagnosticsOpen && <MatchDiagnosticsPanel refreshKey={`${jobKey}:${refresh}:${reviewsChanged}`} queueMs={queue?.query_ms} />}
      </details>
      <div className="match-controls">
        <label>Minimum visual match: {filters.threshold}%
          <input type="range" min="90" max="100" step="1" value={filters.threshold} aria-label="Minimum visual match"
            onChange={(e) => update({ threshold: Number(e.target.value), page: 1, match_page: 1 })} />
        </label>
        <label>Sort <select aria-label="Sort" value={filters.sort} onChange={(e) => update({ sort: e.target.value, page: 1 })}>
          <option value="matches">Most matches</option><option value="newest">Newest</option><option value="oldest">Oldest</option>
          <option value="name">Filename</option><option value="largest">File size</option>
        </select></label>
        <label>Search <input type="search" aria-label="Search filenames" value={filters.q}
          onChange={(e) => update({ q: e.target.value, page: 1 })} /></label>
        <button onClick={reload}>Refresh</button>
      </div>
      {error && <p role="alert" className="error">{error} <button onClick={reload}>Retry</button></p>}
      {loading && <p role="status">Loading matches…</p>}
      <div aria-busy={loading} inert={loading}>
      {queue && (queue.state.unavailable > 0 || queue.state.pending > 0) && <p className="muted">
        {queue.state.unavailable > 0 && <>{plural(queue.state.unavailable, "destination photo")} could not be included because no usable visual hash is recorded. </>}
        {queue.state.pending > 0 && <>{plural(queue.state.pending, "destination photo")} awaiting comparison. Run Index from the Library to finish comparing; these results are partial.</>}
      </p>}
      {matches && <section className="match-detail" aria-label="Photo comparison">
        <div className="match-heading"><h3>Compare with {matches.reference?.filename ?? "unavailable photo"}</h3>
          <button onClick={() => update({ photo: null, match_page: 1 }, true)}>Close comparison</button></div>
        {matches.availability === "not_available" && <p>This photo has no recorded available destination copy. Copy or Move it before reviewing matches. Its history remains in the Library.</p>}
        {matches.availability === "hash_unavailable" && <p>Visual matching is unavailable for this photo because it has no usable visual hash.</p>}
        {matches.reference && <div className="match-reference">{picture(matches.reference, true)}</div>}
        {matches.availability === "available" && <>
          <p>Matches are measured against this reference photo. The largest dimensions are marked for information.</p>
          {matches.total === 0 && <p>No matches at this threshold{matches.state.pending ? "; comparisons are still incomplete" : ""}.</p>}
          <div className="match-grid">{matches.items.map((photo) => picture(photo, true))}</div>{pager(matches, true)}
        </>}
      </section>}
      {queue && <section aria-label="Matching photos">
        {queue.state.photos === 0
          ? <p>No destination photos are available for review. <a href="/" onClick={follow}>Open the Library</a> to Copy or Move indexed photos.</p>
          : queue.total === 0 && <p>No destination photos with matches for these filters.</p>}
        <div className="match-grid">{queue.items.map((photo) => picture(photo))}</div>{pager(queue)}
      </section>}
      </div>
    </main>
    {reviewPair && <MatchReviewDialog key={reviewPair.join(":")} reference={reviewPair[0]} candidate={reviewPair[1]}
      onClose={() => setReviewPair(null)} onSaved={() => setReviewsChanged((n) => n + 1)} />}
  </div>;
}
