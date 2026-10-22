import { useEffect, useRef, useState, type ReactNode } from "react";
import { Modal } from "./ui/Modal";
import { Field } from "./ui/Field";
import { BOOKMARK_REASONS } from "../bookmarks";
import { api, type ReviewDetail } from "../api";

// A decision is acknowledged before the reminder disappears. Selection is untouched.
export function ReviewNote({ id, refreshKey, disabled = false, reason = "all", onResolved, onBusy, compact = false, onOpenReview, actions, onBookmark, concerns = [] }: {
  id: number; refreshKey: number; disabled?: boolean; reason?: string;
  compact?: boolean; onOpenReview?: () => void; actions?: ReactNode; concerns?: { label: string; message: string }[];
  onBookmark?: (preset: string | null) => void;
  onResolved?: (message: string) => void; onBusy?: (busy: boolean) => void;
}) {
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [preset, setPreset] = useState("date");
  const [note, setNote] = useState("");
  const [reload, setReload] = useState(0);
  const pending = useRef<{ detail: ReviewDetail; reason: string; action: string; note: string; request: string; preset?: string } | null>(null);
  useEffect(() => {
    let live = true;
    setError(""); setDetail(null);
    api.review(id).then(d => { if (live) { setDetail(d); onBookmark?.(d.reasons.find(r => r.reason === "later")?.bookmark_reason ?? null); } }, e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [id, refreshKey, reload]);
  const decide = async (why: string, action: string) => {
    if (!detail || busy) return;
    const p = pending.current ?? { detail, reason: why, action, note: action === "later" ? note : "", preset: action === "later" ? preset : undefined, request: Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2,"0")).join("") };
    pending.current = p;
    setBusy(true); onBusy?.(true); setError("");
    try {
      const saved = await api.reviewDecision(id, p.detail, p.reason, p.action, p.note, p.request, p.preset);
      pending.current = null; setDetail(saved); setAdding(false); onBookmark?.(saved.reasons.find(r => r.reason === "later")?.bookmark_reason ?? null);
      const text = p.action === "later" ? "Bookmark saved." : p.action === "keep" ? "Chose to keep this photo. Bookmark removed." : p.action === "done" ? "Bookmark removed." : "Size reviewed. The photo stays in your library.";
      setMessage(p.action === "later" || !onResolved ? text : "");
      window.dispatchEvent(new Event("ns-review-changed"));
      if (p.action !== "later") onResolved?.(text);
    } catch (e) { setError(e instanceof Error ? e.message : "The decision could not be saved."); }
    finally { setBusy(false); onBusy?.(false); }
  };
  const photoActions = detail && detail.location === "Library" && (
      <div className="photo-actions" role="group" aria-label="Photo actions">
        {compact && onOpenReview && (detail.reasons.length > 0 || concerns.length > 0) && <button onClick={onOpenReview}>Inspect photo…</button>}
        {!compact && detail.reasons.filter(n => reason === "all" || n.reason === reason).map(n => <button key={n.reason}
          disabled={busy || disabled || !!pending.current} title={disabled ? "Wait for the running job to finish." : undefined}
          onClick={() => void decide(n.reason, n.reason === "small" ? "reviewed" : n.bookmark_reason === "keep" ? "keep" : "done")}>{n.reason === "small" ? "Mark reviewed" : n.bookmark_reason === "keep" ? "Keep it" : "Remove bookmark"}</button>)}
        {!detail.reasons.some(n => n.reason === "later") && !adding && <button disabled={busy || disabled || !!pending.current}
          title={disabled ? "Wait for the running job to finish." : undefined} onClick={() => setAdding(true)}>Bookmark…</button>}
        {!compact && (reason === "all" || reason === "later") && detail.reasons.some(n => n.bookmark_reason === "keep") &&
          <button disabled={busy || disabled || !!pending.current} onClick={() => void decide("later", "done")}>Remove bookmark</button>}
        {actions}
      </div>
  );
  return <section className="review-note" aria-label="Photo review">
    {detail && detail.location !== "Library" && <p className="section-note">Review actions are available only for organized photos in Library.</p>}
    {detail && detail.location === "Library" && <>
      {compact && photoActions}
      <p className="section-note">Location: {detail.location}</p>
      {(detail.reasons.length > 0 || concerns.length > 0) && <h3>{compact ? "Needs review" : "Why this photo needs review"}</h3>}
      {detail.reasons.filter(n => reason === "all" || n.reason === reason).map(n => <div className="review-reason" key={n.reason}>
        <strong>{n.label}</strong><p>{compact ? (n.reason === "small" ? "Below minimum image size" : n.message) : n.message}</p>
      </div>)}
      {concerns.map(n => <div className="review-reason" key={n.label}><strong>{n.label}</strong><p>{n.message}</p></div>)}
      {!compact && photoActions}
      {!compact && (reason === "all" || reason === "small") && detail.reasons.some(n => n.reason === "small") && <p className="section-note">Mark reviewed clears only the small-image reminder. The photo stays in Library.</p>}
      {!compact && (reason === "all" || reason === "later") && detail.reasons.some(n => n.reason === "later") && <p className="section-note">Removing a bookmark leaves the photo and other review reasons unchanged.</p>}
      {adding && <Modal label="Bookmark photo" onClose={() => setAdding(false)} busy={busy}>
        <h2>Bookmark photo</h2>
        <form className="bookmark-form" onSubmit={e => { e.preventDefault(); void decide("later", "later"); }}>
          <fieldset disabled={busy || !!pending.current}><legend>Why?</legend>
            {Object.entries(BOOKMARK_REASONS).map(([key,label]) => <label className="bookmark-choice" key={key}>
              <input type="radio" name={`bookmark-${id}`} value={key} checked={preset === key} onChange={() => setPreset(key)}/>{label}
            </label>)}
          </fieldset>
          <Field label="Note (optional)" fullWidth value={note} maxLength={60}
            disabled={busy || !!pending.current} onChange={e => setNote(e.target.value)}
            hint={`${note.length} / 60 characters`} />
          {error && <p role="alert" className="error">{error}</p>}
          <div className="settings-actions"><button type="button" disabled={busy} onClick={() => setAdding(false)}>Cancel</button>
            <button className="primary" disabled={busy || disabled} type="submit">{pending.current ? "Retry saving" : "Save bookmark"}</button></div>
        </form>
      </Modal>}
      {detail.history.length > 0 && <details><summary>Review history ({detail.history.length})</summary><ul>{detail.history.map(e => <li key={e.id}>{e.created_at} · {e.reason === "small" ? "Small image marked reviewed" : e.action === "keep" ? "Chose to keep this photo; bookmark removed" : e.action === "done" ? "Bookmark removed" : "Bookmark added"}{e.reason === "later" && ` · ${BOOKMARK_REASONS[e.bookmark_reason ?? "other"] ?? "Other"}`}{e.note ? ` · ${e.note}` : ""}</li>)}</ul></details>}
    </>}
    {message && <p role="status">{message}</p>}
    {error && !adding && <p className="error" role="alert">{error} {pending.current ? <><button disabled={busy} onClick={() => void decide(pending.current!.reason, pending.current!.action)}>Retry saving</button> <button disabled={busy} onClick={() => { pending.current=null; setReload(n=>n+1); }}>Reload review</button></> : <button onClick={() => setReload(n => n + 1)}>Retry loading review</button>}</p>}
  </section>;
}
