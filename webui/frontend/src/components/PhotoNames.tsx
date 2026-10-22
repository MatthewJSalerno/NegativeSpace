import { useEffect, useRef, useState } from "react";
import { api, type PhotoNames, type RenamePreview, type Run } from "../api";
import { follow, logUrl } from "../nav";
import { Modal } from "./ui/Modal";
import { Field } from "./ui/Field";

export function OtherNames({ id, refreshKey, disabled, onChoose }: {
  id: number; refreshKey: number; disabled: boolean; onChoose: (name: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<PhotoNames | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!open) return;
    let live = true; setData(null); setError("");
    api.photoNames(id).then(x => { if (live) setData(x); }, e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [id, open, refreshKey, retry]);
  return <details className="other-names" onToggle={e => setOpen(e.currentTarget.open)}>
    <summary>Also arrived as</summary>
    {!data && !error && <p role="status">Loading recorded names…</p>}
    {error && <p className="error">{error} <button className="link" onClick={() => setRetry(n => n+1)}>Retry</button></p>}
    {data?.candidates.length === 0 && <p>No other recorded names.</p>}
    {data && <ul>{data.candidates.map(x => <li key={x.name}>
      <div className="history-links"><strong>{x.name}</strong><button className="link" disabled={disabled} title={disabled ? "Wait for the running job to finish." : undefined} onClick={() => onChoose(x.name)}>Use this name</button></div>
      {x.seen_at.map(path => <div className="section-note" key={path}><code>{path}</code></div>)}
    </li>)}</ul>}
  </details>;
}

export function RenameDialog({ id, name: initial, onClose, jobRunning }: {
  id: number; name: string; onClose: () => void; jobRunning: boolean;
}) {
  const [name, setName] = useState(initial);
  const [plan, setPlan] = useState<RenamePreview | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<Run | null>(null);
  const [savedPath, setSavedPath] = useState<string | null>(null);
  const completed = useRef(false);
  const running = busy || !!run && ["Preparing", "Running", "Cancelling"].includes(run.status);
  useEffect(() => {
    let live = true; setPlan(null); setError("");
    const timer = setTimeout(() => api.renamePreview(id, name).then(p => { if (live) setPlan(p); }, e => { if (live) setError(e.message); }), 300);
    return () => { live = false; clearTimeout(timer); };
  }, [id, name, retry]);
  useEffect(() => {
    if (!run?.id || completed.current) return;
    let live = true;
    const timer = setTimeout(async () => {
      try {
        if (["Preparing", "Running", "Cancelling"].includes(run.status)) {
          const next = await api.run(run.id!); if (live) setRun(next);
        } else {
          const photo = await api.inspect(id);
          if (!live) return;
          completed.current = true;
          if (run.status === "Completed" && photo.dest_path === plan?.new_path) setSavedPath(photo.dest_path);
          else setError("The rename did not finish as expected. Check the job details before trying again.");
          window.dispatchEvent(new Event("ns-review-changed"));
        }
      } catch (e) { if (live) { setError((e as Error).message); setRun({...run}); } }
    }, running ? 1000 : 0);
    return () => { live = false; clearTimeout(timer); };
  }, [run, id, plan, running]);
  const save = async () => {
    if (!plan || plan.unchanged || running || jobRunning) return;
    setBusy(true); setError("");
    try { setRun(await api.renamePhoto(id, name, plan.token)); }
    catch (e) { setError((e as Error).message); setPlan(null); }
    finally { setBusy(false); }
  };
  return <Modal label="Rename photo" onClose={onClose} busy={running}>
    <h2>{savedPath ? "Photo renamed" : "Rename photo"}</h2>
    {!run && <>
      <Field fullWidth label="Filename" value={name} onChange={e => { setPlan(null); setName(e.target.value); }} autoComplete="off" />
      <p className="section-note">The real extension and date folder stay the same. Any active XMP sidecar follows the photo. Source files stay unchanged.</p>
      {!plan && !error && <p role="status">Checking available filename…</p>}
      {plan && <section aria-label="Rename preview">
        <dl><dt>Current name</dt><dd><code>{plan.current_path.split("/").pop()}</code></dd>
          <dt>Resulting name</dt><dd><code>{plan.new_path.split("/").pop()}</code></dd></dl>
        {plan.collision && <p className="notice">That name is taken. The numbered name above is available; existing files stay untouched.</p>}
        {plan.unchanged && <p className="section-note">No changes needed.</p>}
      </section>}
      {jobRunning && <p className="section-note">Wait for the running job to finish before renaming.</p>}
      <footer className="settings-actions"><button disabled={running} onClick={onClose}>Cancel</button>
        {!plan && error && <button onClick={() => setRetry(n => n+1)}>Refresh preview</button>}
        <button className="primary" disabled={!plan || plan.unchanged || running || jobRunning} onClick={() => void save()}>Rename photo</button></footer>
    </>}
    {run && <>
      <p role="status">{savedPath ? <code>{savedPath.split("/").pop()}</code> : `Job #${run.id} · ${run.status}`}</p>
      <footer className="settings-actions"><a href={logUrl({run:run.id,photo:id})} onClick={follow}>View job details</a><button disabled={running} onClick={onClose}>Close</button></footer>
    </>}
    {error && <p className="error" role="alert">{error}</p>}
  </Modal>;
}
