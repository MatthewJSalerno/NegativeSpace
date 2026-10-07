import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, type ReviewDetail } from "../api";

// A decision is acknowledged before the reminder disappears. Selection is untouched.
export function ReviewNote({ id, refreshKey, disabled = false, reason = "all", onResolved, onBusy, compact = false, onOpenReview, actions, concerns = [] }: {
  id: number; refreshKey: number; disabled?: boolean; reason?: string;
  compact?: boolean; onOpenReview?: () => void; actions?: ReactNode; concerns?: { label: string; message: string }[];
  onResolved?: (message: string) => void; onBusy?: (busy: boolean) => void;
}) {
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [note, setNote] = useState("");
  const [reload, setReload] = useState(0);
  const pending = useRef<{ detail: ReviewDetail; reason: string; action: string; note: string; request: string } | null>(null);
  useEffect(() => {
    let live = true;
    setError(""); setDetail(null);
    api.review(id).then(d => { if (live) setDetail(d); }, e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [id, refreshKey, reload]);
  const decide = async (why: string, action: string) => {
    if (!detail || busy) return;
    const p = pending.current ?? { detail, reason: why, action, note: action === "later" ? note : "", request: Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2,"0")).join("") };
    pending.current = p;
    setBusy(true); onBusy?.(true); setError("");
    try {
      const saved = await api.reviewDecision(id, p.detail, p.reason, p.action, p.note, p.request);
      pending.current = null; setDetail(saved); setAdding(false);
      const text = p.action === "later" ? "Added to Review later." : p.action === "done" ? "Review later reminder cleared." : "Size reviewed. The photo stays in your library.";
      setMessage(p.action === "later" || !onResolved ? text : "");
      window.dispatchEvent(new Event("ns-review-changed"));
      if (p.action !== "later") onResolved?.(text);
    } catch (e) { setError(e instanceof Error ? e.message : "The decision could not be saved."); }
    finally { setBusy(false); onBusy?.(false); }
  };
  return <section className="review-note" aria-label="Photo review">
    {detail && <>
      <p className="section-note">Location: {detail.location}</p>
      {(detail.reasons.length > 0 || concerns.length > 0) && <h3>{compact ? "Needs review" : "Why this photo needs review"}</h3>}
      {detail.reasons.filter(n => reason === "all" || n.reason === reason).map(n => <div className="review-reason" key={n.reason}>
        <strong>{n.label}</strong><p>{compact ? (n.reason === "small" ? "Below minimum image size" : n.message) : n.message}</p>
      </div>)}
      {concerns.map(n => <div className="review-reason" key={n.label}><strong>{n.label}</strong><p>{n.message}</p></div>)}
      <div className="photo-actions" role="group" aria-label="Photo actions">
        {compact && onOpenReview && (detail.reasons.length > 0 || concerns.length > 0) && <button onClick={onOpenReview}>Review photo…</button>}
        {!compact && detail.reasons.filter(n => reason === "all" || n.reason === reason).map(n => <button key={n.reason}
          disabled={busy || disabled || !!pending.current} title={disabled ? "Wait for the running job to finish." : undefined}
          onClick={() => void decide(n.reason, n.reason === "small" ? "reviewed" : "done")}>{n.reason === "small" ? "Mark reviewed" : "Done"}</button>)}
        {!detail.reasons.some(n => n.reason === "later") && !adding && <button disabled={busy || disabled || !!pending.current}
          title={disabled ? "Wait for the running job to finish." : undefined} onClick={() => setAdding(true)}>Review later…</button>}
        {actions}
      </div>
      {!compact && (reason === "all" || reason === "small") && detail.reasons.some(n => n.reason === "small") && <p className="section-note">Mark reviewed clears only the small-image reminder. The photo stays in Library.</p>}
      {!compact && (reason === "all" || reason === "later") && detail.reasons.some(n => n.reason === "later") && <p className="section-note">Done clears only the Review later reminder.</p>}
      {adding && <div className="review-note-form"><label htmlFor={`review-note-${id}`}>Optional note</label><textarea id={`review-note-${id}`} value={note} maxLength={500} disabled={busy} onChange={e => setNote(e.target.value)} />
        <div className="photo-actions"><button disabled={busy || disabled || !!pending.current} onClick={() => void decide("later", "later")}>Save reminder</button> <button disabled={busy} onClick={() => setAdding(false)}>Cancel</button></div></div>}
      {detail.history.length > 0 && <details><summary>Review history ({detail.history.length})</summary><ul>{detail.history.map(e => <li key={e.id}>{e.created_at} · {e.reason === "small" ? "Small image marked reviewed" : e.action === "done" ? "Review later completed" : "Review later added"}{e.note ? ` · ${e.note}` : ""}</li>)}</ul></details>}
    </>}
    {message && <p role="status">{message}</p>}
    {error && <p className="error" role="alert">{error} {pending.current ? <><button disabled={busy} onClick={() => void decide(pending.current!.reason, pending.current!.action)}>Retry saving</button> <button disabled={busy} onClick={() => { pending.current=null; setReload(n=>n+1); }}>Reload review</button></> : <button onClick={() => setReload(n => n + 1)}>Retry loading review</button>}</p>}
  </section>;
}
