import { useEffect, useRef, useState } from "react";
import { api, type BulkReviewAction, type BulkReviewCounts, type BulkReviewPlan, type BulkReviewResult, type ReviewDecision } from "../api";
import { plural } from "../format";
import { Modal } from "./ui/Modal";
import { Pager } from "./Pager";

const actions = {
  small: { reason: "small", label: "Mark reviewed", description: "This clears only the small-image reminders." },
  date: { reason: "date", label: "These dates are correct", description: "This confirms each photo’s own recorded date. The dates stay unchanged." },
  keep: { reason: "later", label: "Keep these photos", description: "This records your decision to keep these photos and removes their keep-decision bookmarks." },
  done: { reason: "later", label: "Remove bookmarks", description: "This removes only the bookmarks. Other review reasons stay." },
};

export function BulkReviewActions({ ids, reason, counts, disabled, onSaved }: {
  ids: number[]; reason: string | null; counts: BulkReviewCounts | null; disabled: boolean; onSaved: (ids: number[]) => void;
}) {
  const [choice, setChoice] = useState<{ action: BulkReviewAction; ids: number[] } | null>(null);
  return <>
    {reason && ids.length > 50000 && <span className="section-note">Select up to 50,000 photos for one review answer.</span>}
    {(Object.keys(actions) as BulkReviewAction[]).filter(key => actions[key].reason === reason && counts?.[key] === ids.length && ids.length > 0).map(key =>
      <button className="photo-action" key={key} disabled={disabled} title={disabled ? "Wait for the running job and its backup to finish." : undefined}
        onClick={() => setChoice({ action: key, ids: [...ids] })}>{actions[key].label}…</button>)}
    {choice && <BulkReviewDialog choice={choice} disabled={disabled} onClose={() => setChoice(null)} onSaved={onSaved} />}
  </>;
}

function BulkReviewDialog({ choice, disabled, onClose, onSaved }: {
  choice: { action: BulkReviewAction; ids: number[] }; disabled: boolean; onClose: () => void; onSaved: (ids: number[]) => void;
}) {
  const [plan, setPlan] = useState<BulkReviewPlan | null>(null);
  const [result, setResult] = useState<BulkReviewResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [page, setPage] = useState(1);
  const pending = useRef<ReviewDecision[] | null>(null);
  const action = actions[choice.action];
  useEffect(() => {
    let live = true;
    setPlan(null); setError("");
    api.previewReviewBatch(choice.ids, choice.action).then(value => { if (live) setPlan(value); }, e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [choice, reload]);
  const save = async () => {
    if (!plan || busy || disabled) return;
    if (!pending.current) {
      const request = Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, "0")).join("");
      pending.current = plan.items.map(item => ({ ...item.decision, request_id: `bulk-${request}-${item.decision.photo_id}` }));
    }
    setBusy(true); setError("");
    try {
      const answer = await api.reviewBatch(pending.current);
      setResult(answer); pending.current = null; setPage(1);
      window.dispatchEvent(new Event("ns-review-changed"));
    } catch (e) { setError(e instanceof Error ? e.message : "The answers could not be confirmed. Retry saving to check the same request."); }
    finally { setBusy(false); }
  };
  const skipped = [...(plan?.skipped ?? []), ...(result?.skipped ?? []).map(row => ({ ...row, filename: plan?.items.find(item => item.decision.photo_id === row.photo_id)?.filename ?? null }))];
  return <Modal role="alertdialog" label={action.label} onClose={() => { if (result) onSaved(result.saved); onClose(); }} busy={busy}>
    <h2>{result ? (result.saved.length ? "Review answers saved" : "No review answers saved") : `${action.label}?`}</h2>
    {!plan && !error && <p role="status">Checking the selected photos…</p>}
    {plan && !result && <><p>{plural(plan.items.length, "photo")} will receive this answer. Their files do not change.</p><p>{action.description}</p></>}
    {result && <p role="status">{plural(result.saved.length, "photo")} answered. Other review reasons and photo files are unchanged.</p>}
    {skipped.length > 0 && <section aria-label="Photos left unchanged">
      <h3>{plural(skipped.length, "photo")} left unchanged</h3>
      <p>These photos stay selected. Check their current information before deciding again.</p>
      <ul>{skipped.slice((page - 1) * 20, page * 20).map(row => <li key={row.photo_id}><strong>{row.filename ?? `Photo #${row.photo_id}`}</strong> — {row.message}</li>)}</ul>
      {skipped.length > 20 && <Pager page={page} pages={Math.ceil(skipped.length / 20)} total={skipped.length} pageSize={20} sizes={[20]} onPage={setPage} onPageSize={() => {}} />}
    </section>}
    {disabled && !result && <p className="warning">Wait for the running job and its backup to finish.</p>}
    {error && <p className="error" role="alert">{error}</p>}
    <footer className="settings-actions">
      <button data-initial-focus disabled={busy} onClick={() => { if (result) onSaved(result.saved); onClose(); }}>{result ? "Close" : "Cancel"}</button>
      {!plan && error && <button onClick={() => setReload(n => n + 1)}>Retry loading</button>}
      {plan && !result && <button className="primary" disabled={busy || disabled || plan.items.length === 0} onClick={() => void save()}>{busy ? "Saving…" : pending.current ? "Retry saving" : action.label}</button>}
    </footer>
  </Modal>;
}
