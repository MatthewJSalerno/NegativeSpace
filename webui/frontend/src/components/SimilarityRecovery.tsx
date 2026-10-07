import { useEffect, useRef, useState } from "react";
import { api, type SimilarityRecoveryPage, type Run } from "../api";
import { plural } from "../format";
import { countsLine, currentPhase, phaseLabel, summary } from "../jobs";
import { Modal } from "./ui/Modal";

export function SimilarityRecovery({ photoId, onRecovered, visible = true }: { photoId?: number; onRecovered?: () => void; visible?: boolean }) {
  const [open, setOpen] = useState(false);
  const [scopePhoto, setScopePhoto] = useState<number | undefined>(photoId);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<SimilarityRecoveryPage | null>(null);
  const [busy, setBusy] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [retry, setRetry] = useState(0);
  const callback = useRef(onRecovered); callback.current = onRecovered;
  const notified = useRef<number | null>(null);
  useEffect(() => {
    if (!open) return;
    let live = true, loading = false;
    setData(null); setBusy(true);
    const load = async () => {
      if (loading) return;
      loading = true;
      try {
        const [next, status, latest] = await Promise.all([api.similarityRecovery(page, scopePhoto), api.status(), run?.id != null ? api.run(run.id) : Promise.resolve(null)]);
        if (!live) return;
        setData(next); setBusy(!!status.active_job && !status.active_job.awaiting_reconciliation); setError(null);
        if (next.total > 0 && page > Math.ceil(next.total / next.page_size)) setPage(Math.ceil(next.total / next.page_size));
        if (latest) {
          setRun(latest);
          if (!["Preparing", "Running", "Cancelling"].includes(latest.status) && notified.current !== latest.id) {
            notified.current = latest.id; callback.current?.();
          }
        }
      } catch (e) { if (live) { setError(e instanceof Error ? e.message : "Recovery status could not be loaded."); setBusy(true); } }
      finally { loading = false; }
    };
    void load();
    const timer = window.setInterval(load, 2000);
    return () => { live = false; window.clearInterval(timer); };
  }, [open, page, scopePhoto, run?.id, retry]);
  const start = async (scope: "missing" | "comparisons", id?: number) => {
    setStarting(true); setError(null);
    try { setRun(await api.repairSimilarity(scope, id)); setBusy(true); setRetry(n => n + 1); }
    catch (e) { setError(e instanceof Error ? e.message : "Recovery could not start."); }
    finally { setStarting(false); }
  };
  const phase = run && currentPhase(run);
  const running = run && ["Preparing", "Running", "Cancelling"].includes(run.status);
  return <>
    {visible && <button className="photo-action" onClick={() => { setScopePhoto(photoId); setPage(1); setOpen(true); }}>Review matching status</button>}
    {open && <Modal label="Matching status" className="dialog" onClose={() => setOpen(false)} busy={starting}>
      <h2>Matching status</h2>
      <p>Generate hashes that have not been created, or resume unfinished comparisons. Files with recorded failures need the correction described below before rechecking. Photo files stay unchanged. Missing EXIF alone does not mean a file is damaged.</p>
      {error && <p className="error" role="alert">{error} <button onClick={() => setRetry(n => n + 1)}>Retry status</button></p>}
      {!data && !error && <p role="status">Loading affected photos…</p>}
      {data && <>
        <p>{plural(data.state.unavailable, "destination photo without a usable visual hash", "destination photos without usable visual hashes")}; {plural(data.state.pending, "photo awaiting comparison", "photos awaiting comparison")}.</p>
        {busy && <p className="section-note">Wait for the running job to finish, or cancel it, before starting recovery.</p>}
        <div className="row-links">
          <button disabled={busy || starting || data.generatable === 0} onClick={() => start("missing", scopePhoto)}>
            Generate missing hashes</button>
          <button disabled={busy || starting || data.state.pending === 0} onClick={() => start("comparisons")}>Resume comparisons</button>
        </div>
        <p className="section-note">Hash recovery verifies each file’s SHA-1 before and after decoding. Unsupported formats need decoder support; files that cannot be decoded need external review. They remain excluded from visual matching. Read the reason below and retry only after fixing its cause.</p>
        {data.total === 0 ? <p>No matching issues in this scope.</p> : <ul className="recovery-photos">
          {data.items.map(item => <li key={item.id}>
            <a href={`/?photo=${item.id}&tab=similar`}>{item.filename}</a>
            <p>{item.message}</p>
            {item.retryable && <button disabled={busy || starting} onClick={() => start("missing", item.id)}>{item.action === "generate" ? "Generate visual hash" : "Recheck file after external fix"}</button>}
          </li>)}
        </ul>}
        {data.total > data.page_size && <nav className="match-pages" aria-label="Affected photo pages">
          <button disabled={page <= 1} onClick={() => setPage(n => n - 1)}>Previous affected photos</button>
          <span>Page {page} of {Math.ceil(data.total / data.page_size)}</span>
          <button disabled={page * data.page_size >= data.total} onClick={() => setPage(n => n + 1)}>Next affected photos</button>
        </nav>}
      </>}
      {run && <div role="status">
        <p>{running ? "Similarity recovery is running" : summary(run).headline}{phase ? ` · ${phaseLabel(phase)}: ${phase.done}${phase.total == null ? "" : ` of ${phase.total}`}` : ""}</p>
        {phase && <p>{countsLine(phase.counts, run.mode)}</p>}
        <a href={`/logs?run=${run.id}`}>View recovery job</a>
        {running && <button disabled={run.status === "Cancelling"} onClick={() => api.cancelJob(run.id!).catch(e => setError(e.message))}>Cancel recovery</button>}
      </div>}
      <button disabled={starting} onClick={() => setOpen(false)}>Close</button>
    </Modal>}
  </>;
}
