import { useEffect, useRef, useState } from "react";
import { api, type MetadataSourceView, type PrimaryPreview, type Run } from "../api";
import { follow, logUrl } from "../nav";
import { Modal } from "./ui/Modal";
import { MetadataFieldTable } from "./MetadataFieldTable";

export function PrimarySourceEditor({ photoId, source, captureId, onClose, onSaved }: {
  photoId: number; source: MetadataSourceView; captureId: number;
  onClose: () => void; onSaved: () => void;
}) {
  const [preview, setPreview] = useState<PrimaryPreview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [run, setRun] = useState<Run | null>(null);
  const [verified, setVerified] = useState(false);
  const saved = useRef(onSaved);
  saved.current = onSaved;
  useEffect(() => {
    let live = true;
    setPreview(null); setError(""); setBusy(true);
    api.primaryPreview(photoId, source.id, captureId).then(value => {
      if (live) setPreview(value);
    }, e => { if (live) setError(e.message); }).finally(() => { if (live) setBusy(false); });
    return () => { live = false; };
  }, [photoId, source.id, captureId, reload]);
  useEffect(() => {
    if (!run || run.id == null) return;
    let live = true;
    const running = ["Preparing", "Running", "Cancelling"].includes(run.status);
    const timer = setTimeout(async () => {
      try {
        if (running) {
          const next = await api.run(run.id!);
          if (live) { setRun(next); setError(""); }
        } else {
          const current = await api.metadata(photoId);
          if (!live) return;
          setVerified(run.status === "Completed" && current.primary_id === source.id);
          if (run.status === "Completed" && current.primary_id !== source.id) {
            setError("The chosen source was not confirmed as primary. Review the job details before trying again.");
          }
          saved.current();
        }
      } catch (e) {
        if (live) { setError((e as Error).message); if (running) setRun({ ...run }); }
      }
    }, running ? 1000 : 0);
    return () => { live = false; clearTimeout(timer); };
  }, [run, photoId, source.id]);
  const save = async () => {
    if (!preview) return;
    setBusy(true); setError("");
    try { setRun(await api.savePrimary(photoId, preview)); }
    catch (e) { setError((e as Error).message); setPreview(null); }
    finally { setBusy(false); }
  };
  return <Modal label="Change primary metadata source" onClose={onClose} busy={busy}>
    <h2>{verified ? "Primary source changed" : "Change primary metadata source"}</h2>
    {!run && <>
      <p>Use <strong>{source.label}{source.version_id != null ? ` · Version ${source.version_id}` : ""}</strong> as primary?</p>
      <p>This source will take priority when organizing this photo and saving future metadata edits. Other recorded sources remain available.</p>
      {busy && !preview && <p role="status">Checking metadata and location…</p>}
      {preview && <>
        {preview.kind === "sidecar_xmp"
          ? <p>The selected XMP version will become the photo’s destination sidecar. The previous version is preserved in history.</p>
          : <p>The photo’s embedded metadata stays unchanged. Future embedded edits are supported for qualified JPEG files only.</p>}
        <section aria-label="Primary change preview">
          <h3>What changes</h3>
          {preview.differences.length > 0 ? <MetadataFieldTable caption="Effective metadata changes"
            fields={preview.differences} primary={preview.before} source={preview.after}
            primaryLabel="Before" sourceLabel="After" /> : <p>The effective metadata values stay the same. Only the primary source changes.</p>}
          <p className="section-note">An absent field may use another source. An explicitly empty field stays empty.</p>
          <dl><dt>Current location</dt><dd><code>{preview.filing.current}</code></dd>
            <dt>Resulting location</dt><dd><code>{preview.filing.proposed}</code></dd></dl>
          <p>{preview.filing.change ? "The photo and any active sidecar will move to the resulting location." : "The photo stays in its current location."}</p>
        </section>
      </>}
      <footer className="settings-actions">
        <button disabled={busy} onClick={onClose}>Cancel</button>
        {preview ? <button className="primary" disabled={busy} onClick={() => void save()}>{busy ? "Submitting…" : preview.filing.change ? "Change primary and move file" : "Change primary"}</button>
          : !busy && <button onClick={() => setReload(n => n + 1)}>Refresh preview</button>}
      </footer>
    </>}
    {run && <>
      <section role="status">
        {verified ? <p>{source.label} is now primary. Future edits use this source.</p>
          : <p>Metadata job #{run.id}: {run.status}</p>}
        {run.status === "Failed" && <p>The change did not finish. Check the job details and any file issue before starting another change.</p>}
      </section>
      <footer className="settings-actions"><a href={logUrl({run:run.id,photo:photoId})} onClick={follow}>View job details</a><button onClick={onClose}>Close</button></footer>
    </>}
    {error && <p className="error" role="alert">{error}</p>}
  </Modal>;
}
