import { useEffect, useRef, useState } from "react";
import { api, type ReviewDetail } from "../api";

// A decision is acknowledged before the reminder disappears. Selection is untouched.
export function ReviewNote({ id, refreshKey, disabled = false, reason = "all", onResolved, onBusy }: {
  id: number; refreshKey: number; disabled?: boolean; reason?: string;
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
      <p className="muted">Location: {detail.location}</p>
      {detail.reasons.filter(n => reason === "all" || n.reason === reason).map(n => <div key={n.reason}>
        <strong>{n.label}</strong><p>{n.message}</p>
        <button disabled={busy || disabled || !!pending.current} title={disabled ? "Wait for the running job to finish." : undefined}
          onClick={() => void decide(n.reason, n.reason === "small" ? "reviewed" : "done")}>{n.reason === "small" ? "Mark reviewed" : "Done"}</button>
        {n.reason === "small" && <> <button className="link" disabled={busy} onClick={() => window.dispatchEvent(new Event("ns-review-settings"))}>Change in Settings</button></>}
      </div>)}
      {!detail.reasons.some(n => n.reason === "later") && !adding && <button disabled={busy || disabled || !!pending.current} onClick={() => setAdding(true)}>Review later</button>}
      {adding && <div><label htmlFor={`review-note-${id}`}>Optional note</label><textarea id={`review-note-${id}`} value={note} maxLength={500} disabled={busy} onChange={e => setNote(e.target.value)} />
        <button disabled={busy || disabled || !!pending.current} onClick={() => void decide("later", "later")}>Save reminder</button> <button disabled={busy} onClick={() => setAdding(false)}>Cancel</button></div>}
      {detail.history.length > 0 && <details><summary>Review history ({detail.history.length})</summary><ul>{detail.history.map(e => <li key={e.id}>{e.created_at} · {e.reason === "small" ? "Small image marked reviewed" : e.action === "done" ? "Review later completed" : "Review later added"}{e.note ? ` · ${e.note}` : ""}</li>)}</ul></details>}
    </>}
    {message && <p role="status">{message}</p>}
    {error && <p className="error" role="alert">{error} {pending.current ? <><button disabled={busy} onClick={() => void decide(pending.current!.reason, pending.current!.action)}>Retry saving</button> <button disabled={busy} onClick={() => { pending.current=null; setReload(n=>n+1); }}>Reload review</button></> : <button onClick={() => setReload(n => n + 1)}>Retry loading review</button>}</p>}
  </section>;
}
