import { SimilarityRecovery } from "./SimilarityRecovery";
import { useEffect, useState } from "react";
import { api, type MatchCounts, type MatchPage, type MatchPhoto, type MatchScope } from "../api";
import { count, plural } from "../format";
import { Thumb } from "./Thumb";
import { MatchDiagnosticsPanel } from "./MatchDiagnosticsPanel";

export type MatchView = { threshold: number; page: number } | null;

// The open Inspector photo stays the reference. Choosing a threshold only changes
// this small, paged list; it never changes the gallery or its explicit selection.
export function PhotoMatches({ id, name, delivered, rejected = false, view, onView, refreshKey, onReview, changes, jobRunning = false, onReject, onKeep }: {
  id: number; name?: string; delivered: boolean; rejected?: boolean; view: MatchView; onView: (view: MatchView) => void; refreshKey: number;
  onReview: (id: number, scope?: MatchScope, page?: number) => void; changes: number;
  // Reject one look-alike, or keep this photo and reject every look-alike at this
  // threshold (webui-spec 7.8); each asks or reviews first.
  jobRunning?: boolean;
  onReject?: (photo: MatchPhoto) => void;
  onKeep?: (threshold: number) => void;
}) {
  const [summary, setSummary] = useState<MatchCounts | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [results, setResults] = useState<MatchPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [diagnostics, setDiagnostics] = useState(false);
  const threshold = view?.threshold;
  const page = view?.page ?? 1;
  useEffect(() => {
    if (!delivered) return;
    let live = true;
    setSummary(null); setSummaryError(null);
    api.matchCounts(id).then((data) => { if (live) setSummary(data); },
      (e) => { if (live) setSummaryError(e instanceof Error ? e.message : "Match counts could not be loaded."); });
    return () => { live = false; };
  }, [id, delivered, refreshKey, changes, retry]);
  useEffect(() => {
    setResults(null); setError(null);
    if (!delivered || threshold == null) return;
    let live = true;
    api.matches(new URLSearchParams({ threshold: String(threshold), page: String(page), page_size: "12" }), id)
      .then((data) => {
        if (!live) return;
        const lastPage = Math.max(1, Math.ceil(data.total / 12));
        if (data.availability === "available" && page > lastPage) onView({ threshold, page: lastPage });
        else setResults(data);
      },
        (e) => { if (live) setError(e instanceof Error ? e.message : "Matches could not be loaded."); });
    return () => { live = false; };
  }, [id, delivered, threshold, page, refreshKey, changes, retry]);

  return <section className="info-section photo-matches" aria-label="Similar photos">
    {!delivered ? <p className="muted">Copy or Move this photo to the destination to review visual matches.</p> : <>
      <p className="section-note">{rejected ? "This photo is in Rejects. Matches are organized photos in Library." : "Matches are organized photos in Library. Rejected matches are shown separately below."} Not organized files aren’t included.</p>
      {summaryError && <p className="error" role="alert">{summaryError} <button onClick={() => setRetry((n) => n + 1)}>Retry match counts</button></p>}
      {!summary && !summaryError && <p role="status">Loading match counts…</p>}
      {summary?.availability === "not_available" && <p>No available destination copy is recorded for this photo.</p>}
      {summary?.availability === "hash_unavailable" && <p>Visual matching is unavailable: this photo has no usable visual hash. </p>}
      {summary?.availability === "available" && <>
        <div className="match-thresholds" role="group" aria-label="Minimum visual similarity">
          {summary.counts.map((c) => <button key={c.threshold} aria-pressed={threshold === c.threshold}
            aria-label={`${c.threshold}% or higher: ${plural(c.count, "match", "matches")}`}
            onClick={() => onView({ threshold: c.threshold, page: 1 })}>
            <strong>{c.threshold === 100 ? "100%" : `${c.threshold}%+`}</strong><span>{count(c.count)}</span>
          </button>)}
        </div>
        <p className="section-note">Counts include all matches at or above each percentage. These measure visual hash similarity, not confidence; even 100% can be different pictures.</p>
        <p className="section-note">Below 90%, results are more likely to be unrelated. Review photos side by side before using them as clues for dates or other details.</p>
        {summary.pending > 0 && <p className="muted">Results are partial: {plural(summary.pending, "destination photo")} awaiting comparison. </p>}
      </>}
      <SimilarityRecovery visible={!rejected && (summary?.availability === "hash_unavailable" || (summary?.pending ?? 0) > 0)}
        photoId={summary?.availability === "hash_unavailable" ? id : undefined} onRecovered={() => setRetry(n => n + 1)} />
      {view && <div className="inspector-matches" aria-label="Matches for this photo" role="region">
        <div className="match-heading"><h4>Matches at {threshold}% or higher</h4>
          <button className="link" onClick={() => onView(null)}>Hide matches</button></div>
        {error && <p className="error" role="alert">{error} <button onClick={() => setRetry((n) => n + 1)}>Retry matches</button></p>}
        {!results && !error && <p role="status">Loading matches…</p>}
        {results?.availability === "available" && <>
          <p className="section-note">{plural(results.total, "potential match", "potential matches")}. Review photos for clues about dates, events and other details.</p>
          {results.total === 0 && <p>No recorded matches at this threshold{results.state.pending ? "; comparisons are incomplete" : ""}.</p>}
          {onKeep && results.total > 0 && <button className="photo-action" disabled={jobRunning}
            title={jobRunning ? "A job is running. Wait for it to finish or cancel it." : `Keep ${name ?? "the reference photo"}. The matches are reviewed before any is rejected.`}
            onClick={() => onKeep(threshold!)}>
            Keep reference, reject {plural(results.total, "match", "matches")}…
          </button>}
          <ul className="inspector-match-list">
            {results.items.map((photo) => <li key={photo.id}>
              <button className="inspector-match" onClick={() => onReview(photo.id, "library", page)} aria-label={`Review side by side: ${photo.filename}`}>
                <Thumb id={photo.id} alt="" refreshKey={refreshKey} />
                <span><strong>{photo.filename}</strong><span>{photo.score}% visual similarity</span>
                  <span className="muted">{photo.width && photo.height ? `${photo.width} × ${photo.height}` : "Dimensions unknown"}</span>
                  <span>Review side by side</span></span>
              </button>
              {onReject && <button className="photo-action" disabled={jobRunning} aria-label={`Reject ${photo.filename}…`}
                title={jobRunning ? "A job is running. Wait for it to finish or cancel it." : `Move ${photo.filename} out of the library into Rejects. Nothing is deleted.`}
                onClick={() => onReject(photo)}>Reject…</button>}
            </li>)}
          </ul>
          {results.total > 12 && <nav className="match-pages" aria-label="Match pages">
            <button disabled={page <= 1} onClick={() => onView({ threshold: threshold!, page: page - 1 })}>Previous matches</button>
            <span>Page {count(page)} of {count(Math.ceil(results.total / 12))}</span>
            <button disabled={page >= Math.ceil(results.total / 12)} onClick={() => onView({ threshold: threshold!, page: page + 1 })}>Next matches</button>
          </nav>}
        </>}
        {results && results.availability !== "available" && <p>Matches are unavailable for this photo. Its recorded destination copy and visual hash are required.</p>}
      </div>}
      {!rejected && delivered && threshold != null && summary?.availability === "available" && <RejectedMatches
        key={`${id}:${threshold}`} id={id} threshold={threshold} refreshKey={`${refreshKey}:${changes}:${retry}`}
        onReview={onReview} />}
      <details onToggle={(e) => setDiagnostics(e.currentTarget.open)}><summary>Validation and performance</summary>
        {diagnostics && <MatchDiagnosticsPanel refreshKey={`${refreshKey}:${retry}:${changes}`} />}
      </details>
    </>}
  </section>;
}

// Rejected candidates are an explicit, separately paged scope. They never enter
// the Library count buttons or the Keep-reference selection.
function RejectedMatches({ id, threshold, refreshKey, onReview }: {
  id: number; threshold: number; refreshKey: string;
  onReview: (id: number, scope: MatchScope, page: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [results, setResults] = useState<MatchPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let live = true;
    setResults(null); setError(null);
    api.matches(new URLSearchParams({ scope: "rejects", threshold: String(threshold), page: String(page), page_size: "12" }), id)
      .then(data => {
        if (!live) return;
        const last = Math.max(1, Math.ceil(data.total / 12));
        if (page > last) setPage(last); else setResults(data);
      }, e => { if (live) setError(e instanceof Error ? e.message : "Rejected matches could not be loaded."); });
    return () => { live = false; };
  }, [id, threshold, page, refreshKey, retry]);
  if (error) return <p role="alert" className="error">{error} <button onClick={() => setRetry(n => n + 1)}>Retry rejected matches</button></p>;
  if (!results) return <p role="status" className="section-note">Checking matches in Rejects…</p>;
  if (!results.total) return null;
  return <section className="info-section" aria-label="Matches in Rejects">
    <button className="photo-action" aria-expanded={open} onClick={() => setOpen(value => !value)}>
      Also matches {plural(results.total, "photo")} in Rejects
    </button>
    {open && <>
      <p className="section-note">At {threshold}% or higher. Comparing does not reject or return either photo.</p>
      <ul className="inspector-match-list">{results.items.map(photo => <li key={photo.id}>
        <button className="inspector-match" onClick={() => onReview(photo.id, "rejects", page)} aria-label={`Review side by side: ${photo.filename}`}>
          <Thumb id={photo.id} alt="" refreshKey={retry} />
          <span><strong>{photo.filename}</strong><span>Location: Rejects</span>
            <span>{photo.score}% visual similarity</span><span>Review side by side</span></span>
        </button>
      </li>)}</ul>
      {results.total > 12 && <nav className="match-pages" aria-label="Rejected match pages">
        <button disabled={page <= 1} onClick={() => setPage(n => n - 1)}>Previous rejected matches</button>
        <span>Page {count(page)} of {count(Math.ceil(results.total / 12))}</span>
        <button disabled={page >= Math.ceil(results.total / 12)} onClick={() => setPage(n => n + 1)}>Next rejected matches</button>
      </nav>}
    </>}
  </section>;
}
