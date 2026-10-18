import { DuplicateEditNotice } from "./DuplicateEditNotice";
import { useEffect, useRef, useState } from "react";
import { api, type RotationPlan, type Run } from "../api";
import { follow, logUrl } from "../nav";

type Item = RotationPlan["items"][number];
const isRunning = (run: Run) => ["Preparing", "Running", "Cancelling"].includes(run.status);

// Owned by the workspace, so moving between previews never loses a running save.
export function useRotationSave(onSaved: (id: number, survivor?: number) => void) {
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState("");
  const [photoId, setPhotoId] = useState<number | null>(null);
  const [saved, setSaved] = useState(false);
  const submitted = useRef<Item | null>(null);
  const callback = useRef(onSaved); callback.current = onSaved;
  const finish = async (result: Run) => {
    setRun(result);
    try {
      const item = submitted.current!;
      const metadata = await api.metadata(item.photo_id);
      const primary = metadata.sources.find(s => s.id === metadata.primary_id);
      const retired = !item.duplicate || ["Duplicate", "Removed_Duplicate"].includes((await api.inspect(item.photo_id)).status);
      if (metadata.applied && primary?.fields.orientation === item.after) {
        setSaved(true); callback.current(item.photo_id, retired ? item.duplicate?.photo_id : undefined);
        if (!retired) setError("Duplicate cleanup did not finish. Check the job details before trying again.");
        window.dispatchEvent(new Event("ns-review-changed"));
      } else setError("Rotation was not confirmed. Check the job details before trying again.");
    } catch { setError("Could not confirm the saved rotation. Check the job details before trying again."); }
    finally { setBusy(false); }
  };
  useEffect(() => {
    if (!run || !isRunning(run)) return;
    let live = true;
    const timer = setTimeout(() => api.run(run.id!).then(next => {
      if (!live) return;
      if (isRunning(next)) setRun(next); else void finish(next);
    }, e => { if (live) { setError(e.message); setRun({ ...run }); } }), 1000);
    return () => { live = false; clearTimeout(timer); };
  }, [run]);
  const save = async (item: Item) => {
    if (busy || !item.edit || item.error || item.no_change) return;
    submitted.current = item; setPhotoId(item.photo_id); setSaved(false); setBusy(true); setError(""); setRun(null);
    try {
      const accepted = await api.saveRotations([item.edit]);
      setRun(accepted);
      if (!isRunning(accepted)) await finish(accepted);
    } catch (e) { setError((e as Error).message); setBusy(false); }
  };
  return { busy, run, error, photoId, saved, save };
}
export type RotationSave = ReturnType<typeof useRotationSave>;

export function RotationControls({ id, label, turns, onChange, saver, jobRunning, refreshKey }: {
  id: number; label: string; turns: number; onChange: (turns: number) => void;
  saver: RotationSave; jobRunning: boolean; refreshKey: number;
}) {
  const [plan, setPlan] = useState<Item | null>(null);
  const [confirmDuplicate, setConfirmDuplicate] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    setPlan(null); setError(""); setConfirmDuplicate(false);
    if (!turns || saver.busy) return;
    let live = true;
    api.rotationPreview([{ photo_id: id, turns }]).then(p => { if (live) setPlan(p.items[0]); }, e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [id, turns, refreshKey, retry, saver.busy]);
  const own = saver.photoId === id;
  const target = plan?.target;
  return <div className="inline-rotation">
    <div className="photo-actions" role="group" aria-label={`${label} rotation`}>
      <button className="photo-action rotation-arrow" aria-label={`Rotate ${label.toLowerCase()} left`} title="Rotate left" disabled={saver.busy} onClick={() => onChange((turns + 3) % 4)}>↶</button>
      <button className="photo-action rotation-arrow" aria-label={`Rotate ${label.toLowerCase()} right`} title="Rotate right" disabled={saver.busy} onClick={() => onChange((turns + 1) % 4)}>↷</button>
      <span className="rotation-save-actions" style={{ visibility: turns ? undefined : "hidden" }}>
        <button className="primary" disabled={!turns || saver.busy || jobRunning || !plan?.edit || !!plan.error || plan.no_change} onClick={() => { if (plan?.duplicate) setConfirmDuplicate(true); else if (plan) void saver.save(plan); }}>Save rotation</button>
        <button disabled={!turns || saver.busy} onClick={() => onChange(0)}>Reset</button>
      </span>
    </div>
    {confirmDuplicate && plan?.duplicate && <section aria-label="Confirm identical photo">
      <DuplicateEditNotice duplicate={plan.duplicate}/>
      <div className="settings-actions"><button disabled={saver.busy} onClick={() => setConfirmDuplicate(false)}>Cancel</button>
        <button className="primary" disabled={saver.busy || jobRunning} onClick={() => void saver.save(plan)}>Save and keep existing photo</button></div>
    </section>}
    <p className="section-note rotation-guidance" role="status">{own && saver.busy ? "Saving rotation…" : turns ?
      error || plan?.error || (target ? `Temporary turn · Save to ${target.kind === "sidecar_xmp" ? "XMP Sidecar" : target.kind === "embedded_xmp" ? "Embedded XMP" : "EXIF"}${target.create ? " (new sidecar)" : ""}.` : "Checking save target…") : own && saver.saved ? "Rotation saved." : "Turns stay temporary until saved."}
      {turns !== 0 && jobRunning && !saver.busy && " Wait for the running job to finish."}
      {error && <button className="link" onClick={() => setRetry(n => n+1)}>Retry</button>}
      {own && saver.error && <span className="error"> {saver.error}</span>}
      {own && saver.run && <> <a href={logUrl({run:saver.run.id})} onClick={follow}>View job details</a></>}
    </p>
  </div>;
}
