import { useEffect, useRef, useState } from "react";
import { api, type FileIssue } from "../api";
import { useJobFeed } from "../jobs";

// One recovery control in Inspector, Logs and the Library review workspace.
export function FileIssues({ photoId, initialIssues, operationId, onResolved }: {
  photoId: number; initialIssues: FileIssue[]; operationId?: number; onResolved?: () => void;
}) {
  const [issues, setIssues] = useState(initialIssues);
  const [run, setRun] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const pending = useRef<{ issue: number; request: string } | null>(null);
  const { jobs } = useJobFeed();
  useEffect(() => { setIssues(initialIssues); }, [initialIssues]);
  const reload = async () => {
    const data = await api.fileIssues(photoId);
    const current = operationId == null ? data.items : data.items.filter(i => i.operation_id === operationId);
    setIssues(current);
    if (!current.length) { pending.current=null; setRun(null); setBusy(false); }
    return current;
  };
  useEffect(() => {
    if (run == null || jobs.active || jobs.last?.id !== run) return;
    let live = true;
    reload().then(current => {
      if (!live) return;
      setRun(null); setBusy(false);
      setMessage(current.length ? (jobs.last?.status === "Completed" ? "Check finished. The issue remains open; see the explanation below." : "Check stopped. The issue remains open.") : "File verified. The issue is resolved.");
      window.dispatchEvent(new Event("ns-review-changed"));
      if (!current.length) onResolved?.();
    }, e => { if(live) {setBusy(false);setError(e.message);} });
    return () => {live=false;};
  }, [run, jobs.active, jobs.last?.id]);
  const check = async (issue: number) => {
    const request = pending.current ?? {issue,request:Array.from(crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,"0")).join("")};
    pending.current=request; setBusy(true); setError(""); setMessage("");
    try {
      const accepted = await api.checkIssue(request.issue,request.request);
      if (accepted.id == null) throw new Error("The check was not confirmed. Retry with the same request.");
      pending.current=null; setRun(accepted.id);
    } catch(e) {setBusy(false);setError(e instanceof Error ? e.message : "The check was not confirmed.");}
  };
  if (!issues.length && !message && !error) return null;
  return <section className="notice" aria-label="File issues">
    {issues.length > 0 && <>
      <h3>File needs checking</h3>
      <p>An earlier operation could not be verified. Checking updates the catalog; it does not move, overwrite or delete photos.</p>
      {issues.map(issue => <div key={issue.issue_id}>
        <p>{issue.summary}</p>
        <button className="photo-action" disabled={busy || !!jobs.active} title={jobs.active ? "Wait for the running job to finish." : undefined}
          onClick={()=>void check(issue.issue_id)}>{busy ? "Checking…" : pending.current ? "Retry check" : "Check it now"}</button>
        <details><summary>Recorded evidence</summary>
          {issue.evidence.length === 0 ? <p>No detailed observations were recorded for this operation.</p>
          : <ul>{issue.evidence.map((e,i)=><li key={i}><strong>{e.location}</strong>: {e.result} ({e.kind}) · {e.observed_at}<br/><code>{e.path}</code></li>)}</ul>}
        </details>
      </div>)}
    </>}
    {busy && <p role="status">Checking the recorded files. You can follow or cancel this job in the job panel.</p>}
    {message && <p role="status">{message}</p>}
    {error && <p className="error" role="alert">{error} <button onClick={()=>void reload().then(()=>setError(""),e=>setError(e.message))}>Reload issues</button></p>}
  </section>;
}
