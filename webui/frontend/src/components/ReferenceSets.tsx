import { useEffect, useState } from "react";
import { api, MATCH_THRESHOLDS, type ReferenceSetsPage } from "../api";
import { plural } from "../format";
import { Thumb } from "./Thumb";
import { Modal } from "./ui/Modal";

export function ReferenceSets({ reference, threshold, refreshKey, suspended, onThreshold, onClose, onReview }: {
  reference: number; threshold: number; refreshKey: number; suspended: boolean;
  onThreshold: (threshold: number) => void; onClose: () => void;
  onReview: (reference: number, candidate: number | null) => void;
}) {
  const [included, setIncluded] = useState<number[]>([]);
  const [draft, setDraft] = useState<number[]>([]);
  const [page, setPage] = useState(1);
  const [relatedPage, setRelatedPage] = useState(1);
  const [data, setData] = useState<ReferenceSetsPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (suspended) return;
    let live = true;
    setData(null); setError(null);
    api.referenceSets(reference, threshold, included, page, relatedPage).then(
      next => { if (live) setData(next); },
      e => { if (live) setError(e instanceof Error ? e.message : "Sets could not be loaded."); });
    return () => { live = false; };
  }, [reference, threshold, included, page, relatedPage, refreshKey, retry, suspended]);
  const reset = () => { setIncluded([]); setDraft([]); setPage(1); setRelatedPage(1); };
  if (suspended) return null;
  const names = new Map(data?.references.map(r => [r.id, r.filename]));
  const same = draft.length === included.length && draft.every(i => included.includes(i));
  return <Modal label="Explore reference sets" className="dialog reference-sets" onClose={onClose}>
    <div className="settings-head"><h2>Explore reference sets</h2><button onClick={onClose}>Back to gallery</button></div>
    <p>Sets overlap. Each contains a reference and its direct matches from the destination library, including outside gallery filters. References are not keeper recommendations.</p>
    <div className="row-links">
      <label>Matches at or above <select aria-label="Set match threshold" value={threshold} onChange={e => { reset(); onThreshold(Number(e.target.value)); }}>
        {MATCH_THRESHOLDS.map(t => <option key={t} value={t}>{t}%</option>)}
      </select></label>
      <button onClick={() => { reset(); setRetry(n => n + 1); }}>Reset to this set</button>
    </div>
    <p className="section-note">Display choices last until you close this exploration or reload. Changing the percentage clears related sets. No groups or tags are saved.{threshold < 90 && " Below 90%, matches are more likely to be unrelated."}</p>
    {error && <p className="error" role="alert">{error} <button onClick={() => setRetry(n => n + 1)}>Retry sets</button></p>}
    {!data && !error && <p role="status">Loading reference sets…</p>}
    {data && <>
      {(data.state.pending > 0 || data.state.unavailable > 0) && <p className="notice">Sets may be incomplete: {plural(data.state.pending, "photo awaiting comparison", "photos awaiting comparison")}; {plural(data.state.unavailable, "photo without a usable visual hash", "photos without usable visual hashes")}. <a href={`/?photo=${reference}&tab=similar`}>Open matching information and recovery</a></p>}
      <section aria-label="Displayed sets">
        <h3>{included.length ? "Showing selected sets together" : "Reference set"}</h3>
        <ul className="set-reference-list">{data.references.map(r => <li key={r.id}>
          <Thumb id={r.id} alt="" refreshKey={refreshKey} />
          <div><strong>{r.id === reference ? "Starting reference: " : "Related reference: "}{r.filename}</strong><p>{plural(r.total, "photo")} in this set</p></div>
          <button aria-label={`Review this set: ${r.filename}`} disabled={r.total < 2} onClick={() => onReview(r.id, null)}>Review this set</button>
        </li>)}</ul>
        <p>{plural(data.total, "distinct photo")} across the displayed sets. A photo appears once below, even when it belongs to several sets.</p>
        <ul className="set-members">{data.items.map(item => {
          const via = item.references.filter(id => id !== reference);
          const reviewer = item.direct && item.id !== reference ? reference : via.find(id => id !== item.id);
          return <li key={item.id} data-member-id={item.id}>
            <Thumb id={item.id} alt={item.filename} refreshKey={refreshKey} />
            <strong>{item.filename}</strong>
            <p className="section-note">{item.id === reference ? "Starting reference" : item.direct
              ? `Direct match to ${data.reference.filename} · ${item.score}%`
              : `Related through ${via.map(id => names.get(id)).join(", ")} · no direct match recorded at ${threshold}% or higher for ${data.reference.filename}.`}</p>
            <p className="section-note">In sets: {item.references.map(id => names.get(id)).join(", ")}</p>
            {reviewer != null && <button onClick={() => onReview(reviewer, item.id)}>Compare with {names.get(reviewer)}</button>}
          </li>;
        })}</ul>
        <nav className="match-pages" aria-label="Set photo pages">
          <button disabled={data.page <= 1} onClick={() => setPage(data.page - 1)}>Previous photos</button>
          <span>Page {data.page} of {Math.max(1, Math.ceil(data.total / data.page_size))}</span>
          <button disabled={data.page * data.page_size >= data.total} onClick={() => setPage(data.page + 1)}>Next photos</button>
        </nav>
      </section>
      <section aria-label="Related sets">
        <h3>Overlapping sets</h3>
        <p>These references directly match {data.reference.filename}. Their sets overlap this set and may add other photos. Choose up to {data.max_related} related sets to show together; nothing expands automatically.</p>
        <p className="section-note">These checkboxes only choose sets to display. They do not select photos for actions.</p>
        <div className="row-links"><button className="primary" disabled={same} onClick={() => { setIncluded([...draft]); setPage(1); }}>Show together</button>
          <span>{plural(draft.length, "related set")} chosen</span>
          <button disabled={draft.length === 0} onClick={() => setDraft([])}>Clear chosen sets</button></div>
        {data.related.length === 0 && <p>No overlapping sets are currently recorded at this percentage.</p>}
        <ul className="set-reference-list">{data.related.map(r => <li key={r.id} data-related-id={r.id}>
          <label><input type="checkbox" checked={draft.includes(r.id)} disabled={!draft.includes(r.id) && draft.length >= data.max_related}
            onChange={e => setDraft(old => e.target.checked ? [...old,r.id] : old.filter(i => i !== r.id))} aria-label={`Include set: ${r.filename}`} /></label>
          <Thumb id={r.id} alt="" refreshKey={refreshKey} />
          <div><strong>{r.filename}</strong><p className="section-note">{plural(r.total, "photo")} · {r.additional > 0 ? `${plural(r.additional, "additional match", "additional matches")} outside the starting set` : "All members are already in the starting set"}.</p></div>
          <button aria-label={`Review this set: ${r.filename}`} onClick={() => onReview(r.id, null)}>Review this set</button>
        </li>)}</ul>
        <nav className="match-pages" aria-label="Related set pages">
          <button disabled={data.related_page <= 1} onClick={() => setRelatedPage(data.related_page - 1)}>Previous sets</button>
          <span>Page {data.related_page} of {Math.max(1,Math.ceil(data.related_total / data.page_size))}</span>
          <button disabled={data.related_page * data.page_size >= data.related_total} onClick={() => setRelatedPage(data.related_page + 1)}>Next sets</button>
        </nav>
      </section>
    </>}
  </Modal>;
}
