import { useEffect, useState } from "react";
import { api, type MatchReview, type MatchVerdict } from "../api";
import { bytes, instant } from "../format";
import { Thumb } from "./Thumb";
import { Modal } from "./ui/Modal";

const VERDICTS: [MatchVerdict, string][] = [
  ["same", "Same photograph"], ["related", "Related photograph"], ["unrelated", "Unrelated"],
];

export function MatchReviewDialog({ reference, candidate, onClose, onSaved }: {
  reference: number; candidate: number; onClose: () => void; onSaved: () => void;
}) {
  const [review, setReview] = useState<MatchReview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [x, setX] = useState(50);
  const [y, setY] = useState(50);
  useEffect(() => {
    let live = true;
    setReview(null); setError(null);
    api.matchReview(reference, candidate).then((r) => { if (live) setReview(r); },
      (e) => { if (live) setError(e instanceof Error ? e.message : "The comparison could not be loaded."); });
    return () => { live = false; };
  }, [reference, candidate, reload]);
  const save = async (verdict: MatchVerdict | null) => {
    if (!review) return;
    setBusy(true); setError(null);
    try { setReview(await api.saveMatchReview(review, verdict)); onSaved(); }
    catch (e) { setError(e instanceof Error ? e.message : "Your review could not be saved. Refresh and try again."); }
    finally { setBusy(false); }
  };
  return <Modal label="Review photo match" className="dialog match-review-dialog" onClose={onClose} busy={busy}>
    <div className="match-heading"><h2>Review photo match</h2><button onClick={onClose} disabled={busy}>Close review</button></div>
    <p>Compare these photos, then record your judgment. Feedback does not change photos or matching results.</p>
    {error && <p className="error" role="alert">{error}</p>}
    <button onClick={() => setReload((n) => n + 1)} disabled={busy}>Refresh comparison</button>
    {!review && !error && <p role="status">Loading comparison…</p>}
    {review && <>
      <p>{review.exact ? "Identical bytes (same SHA-1)." : "Different bytes (different SHA-1)."} {review.score === null
        ? "Visual hash unavailable." : `Hash similarity ${review.score}% · ${review.distance} of 64 bits differ.`}</p>
      <p className="muted">Hash similarity is not a confidence estimate. Even 100% can describe different pictures.</p>
      <div className="match-controls">
        <label>Zoom both previews: {zoom}×<input aria-label="Zoom both previews" type="range" min="1" max="4" step="0.25"
          value={zoom} onChange={(e) => setZoom(Number(e.target.value))} /></label>
        <label>Horizontal position<input aria-label="Horizontal position" type="range" min="0" max="100" value={x}
          onChange={(e) => setX(Number(e.target.value))} disabled={zoom === 1} /></label>
        <label>Vertical position<input aria-label="Vertical position" type="range" min="0" max="100" value={y}
          onChange={(e) => setY(Number(e.target.value))} disabled={zoom === 1} /></label>
        <button onClick={() => { setZoom(1); setX(50); setY(50); }}>Reset view</button>
      </div>
      <div className="review-pair">
        {[review.reference, review.candidate].map((photo, i) => <figure key={photo.id}>
          <div className="review-viewport"><div className="review-zoom" style={{ transform: `scale(${zoom})`, transformOrigin: `${x}% ${y}%` }}>
            <Thumb id={photo.id} size="preview" alt={`${i === 0 ? "Reference" : "Candidate"}: ${photo.filename}`} refreshKey={reload} />
          </div></div>
          <figcaption><strong>{i === 0 ? "Reference" : "Candidate"}: {photo.filename}</strong><br />
            {photo.width && photo.height ? `${photo.width} × ${photo.height}` : "Dimensions unknown"} · {bytes(photo.file_size)}</figcaption>
        </figure>)}
      </div>
      <p className="muted">Zoom enlarges the generated previews (up to 1024 pixels), not the original files.</p>
      {!review.exact && <fieldset disabled={busy || !!error} className="review-verdicts"><legend>Your judgment</legend>
        {VERDICTS.map(([value, label]) => <button key={value} aria-pressed={review.feedback?.verdict === value}
          onClick={() => save(value)}>{label}</button>)}
        <button disabled={!review.feedback} onClick={() => save(null)}>Clear judgment</button>
      </fieldset>}
      <p role="status">{busy ? "Saving judgment…" : review.feedback
        ? `Saved: ${VERDICTS.find(([value]) => value === review.feedback?.verdict)?.[1]} · ${instant(review.feedback.updated_at)}`
        : "No judgment recorded."}</p>
    </>}
  </Modal>;
}
