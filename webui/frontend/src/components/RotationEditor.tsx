import { DuplicateEditNotice } from "./DuplicateEditNotice";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, type RotationChoice, type RotationPlan, type Run } from "../api";
import { guardNavigation, navigate, follow, logUrl } from "../nav";
import { Modal } from "./ui/Modal";
import { Thumb } from "./Thumb";

export function RotationEditor({ initial, onClose, onSaved, onDiscard, jobRunning = false }: {
  initial: RotationChoice[]; onClose: () => void; onSaved: (ids: number[]) => void;
  onDiscard?: () => void; jobRunning?: boolean;
}) {
  const [choices, setChoices] = useState(initial);
  const [plan, setPlan] = useState<RotationPlan | null>(null);
  const [selected, setSelected] = useState(new Set(initial.map(x => x.photo_id)));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<Run | null>(null);
  const [page, setPage] = useState(0);
  const [reload, setReload] = useState(0);
  const [discard, setDiscard] = useState(false);
  const [saved, setSaved] = useState<number[]>([]);
  const submitted = useRef<RotationPlan["items"]>([]);
  const bypass = useRef(false);
  const leaving = useRef<string | null>(null);
  const dirty = !run && choices.some(x => x.turns !== 0);
  const running = busy || !!run && ["Preparing", "Running", "Cancelling"].includes(run.status);
  useEffect(() => {
    let live = true; setPlan(null); setError("");
    api.rotationPreview(choices).then(p => { if (live) setPlan(p); }, e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [choices, reload]);
  useLayoutEffect(() => {
    if (onDiscard || (!dirty && !running)) return;
    const location = window.location.pathname + window.location.search;
    const unload = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    const unguard = guardNavigation(() => {
      if (bypass.current) return true;
      leaving.current = window.location.pathname + window.location.search;
      window.history.replaceState(null, "", location);
      if (!running) setDiscard(true);
      return false;
    });
    window.addEventListener("beforeunload", unload);
    return () => { unguard(); window.removeEventListener("beforeunload", unload); };
  }, [dirty, running]);
  const finish = async (result: Run) => {
    // A batch may partly succeed. Reset only turns whose target value was verified,
    // so successfully saved photos do not get a second temporary turn on top.
    const confirmed = await Promise.all(submitted.current.map(async item => {
      try {
        const m = await api.metadata(item.photo_id);
        const primary = m.sources.find(s => s.id === m.primary_id);
        return m.applied && primary?.fields.orientation === item.after ? item.photo_id : null;
      } catch { return null; }
    }));
    const ids = confirmed.filter((id): id is number => id != null);
    setSaved(ids); onSaved(ids); setRun(result);
  };
  useEffect(() => {
    if (!run?.id || !["Preparing", "Running", "Cancelling"].includes(run.status)) return;
    let live = true;
    const timer = setTimeout(() => api.run(run.id!).then(async next => {
      if (!live) return;
      if (["Preparing", "Running", "Cancelling"].includes(next.status)) setRun(next);
      else await finish(next);
    }, e => { if (live) { setError(e.message); setRun({ ...run }); } }), 1000);
    return () => { live = false; clearTimeout(timer); };
  }, [run]);
  const close = () => { if (dirty && !onDiscard) setDiscard(true); else onClose(); };
  const turnable = new Set(plan?.items.filter(item => !item.error && selected.has(item.photo_id)).map(item => item.photo_id) ?? []);
  const turn = (delta: number | null) => {
    setChoices(old => old.map(item => turnable.has(item.photo_id)
      ? { ...item, turns: delta == null ? 0 : (item.turns + delta) % 4 } : item));
  };
  const eligible = plan?.items.filter(x => !x.error && !x.no_change && selected.has(x.photo_id)) ?? [];
  const save = async () => {
    setBusy(true); setError("");
    try {
      submitted.current = eligible;
      const accepted = await api.saveRotations(eligible.map(x => x.edit!));
      setRun(accepted);
      if (!["Preparing", "Running", "Cancelling"].includes(accepted.status)) await finish(accepted);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const items = plan?.items.slice(page * 12, (page + 1) * 12) ?? [];
  return <>
    <Modal label="Save rotations" onClose={close} busy={running}>
      <h2>{run ? "Rotation job" : "Save rotations"}</h2>
      {!run && <>
        <p>Save Orientation to each photo’s metadata source. The image pixels and source files stay unchanged.</p>
        <div className="photo-actions" role="group" aria-label="Viewing rotation">
          <button disabled={running || !turnable.size} onClick={() => turn(3)}>↶ Left</button>
          <button disabled={running || !turnable.size} onClick={() => turn(1)}>↷ Right</button>
          <button disabled={running || !turnable.size} onClick={() => turn(2)}>180°</button>
          <button disabled={running || !turnable.size} onClick={() => turn(null)}>Reset turns</button>
        </div>
        <p className="section-note">Only checked photos turn or reset. Select at least one photo to use the controls. Turns stay temporary until you save. A new XMP sidecar contains only Orientation. Your gallery must support sidecar Orientation to display those turns.</p>
        {!plan && !error && <p role="status">Checking rotation targets…</p>}
        <ul className="rotation-list" aria-label="Photos to rotate">
          {items.map(item => <li key={item.photo_id}>
            <div className="rotation-sample"><div style={{ transform: `rotate(${item.turns * 90}deg)` }}><Thumb id={item.photo_id} alt={item.filename}/></div></div>
            <div><label className="checkbox-row"><input type="checkbox" checked={selected.has(item.photo_id)} disabled={!!item.error || running}
              onChange={e => setSelected(old => { const next = new Set(old); e.target.checked ? next.add(item.photo_id) : next.delete(item.photo_id); return next; })}/><strong>{item.filename}</strong></label>
              <p className="section-note">{item.error ?? `${item.turns * 90}° clockwise · ${item.target?.kind === "sidecar_xmp" ? "XMP Sidecar" : item.target?.kind === "embedded_xmp" ? "Embedded XMP" : "EXIF"}${item.target?.create ? " (new sidecar)" : ""}${item.no_change ? " · No changes" : ""}`}</p>
              {item.duplicate && !item.no_change && <DuplicateEditNotice duplicate={item.duplicate}/>}
            </div>
          </li>)}
        </ul>
        {plan && plan.items.length > 12 && <nav className="photo-actions" aria-label="Rotation photos"><button disabled={page === 0} onClick={() => setPage(n => n-1)}>Previous photos</button><span>Page {page + 1} of {Math.ceil(plan.items.length / 12)}</span><button disabled={(page+1)*12 >= plan.items.length} onClick={() => setPage(n => n+1)}>Next photos</button></nav>}
        {jobRunning && <p className="section-note">Wait for the running job to finish before saving.</p>}
        <p className="section-note">The engine verifies the files before writing. Unsupported JPEG structures, including motion photos, are refused without changing their primary source.</p>
        {eligible.some(item => item.duplicate) && <p className="notice">Saving also keeps the named existing photos and removes {eligible.filter(item => item.duplicate).length} redundant edited copies after verification.</p>}
        <footer className="settings-actions">
          <button onClick={close}>Return to photo</button>
          {onDiscard && <button onClick={onDiscard}>Discard viewing turns and leave</button>}
          <button className="primary" disabled={running || jobRunning || !eligible.length} onClick={() => void save()}>Save {eligible.length || "selected"} rotation{eligible.length === 1 ? "" : "s"}</button>
        </footer>
      </>}
      {run && <>
        <p role="status">{running ? `Job #${run.id} · Saving rotations…` : `${saved.length} rotation${saved.length === 1 ? "" : "s"} saved. Job #${run.id} · ${run.status}.`}</p>
        {!running && run.status !== "Completed" && <p>Check the job details for files that were not saved. Their viewing turns remain temporary.</p>}
        <footer className="settings-actions"><a href={logUrl({ run: run.id })} onClick={follow}>View job details</a><button disabled={running} onClick={onClose}>Return to photo</button></footer>
      </>}
      {error && <p className="error" role="alert">{error} {!run && <button className="link" onClick={() => setReload(n => n+1)}>Refresh preview</button>}</p>}
    </Modal>
    {discard && <Modal label="Discard viewing turns?" onClose={() => setDiscard(false)}>
      <h2>Discard viewing turns?</h2><p>No rotation has been saved.</p>
      <footer className="settings-actions"><button onClick={() => { leaving.current = null; setDiscard(false); }}>Keep reviewing</button><button onClick={() => { bypass.current = true; onClose(); if (leaving.current) navigate(leaving.current, true); }}>Discard</button></footer>
    </Modal>}
  </>;
}

// One exit decision for all photos turned in a workspace, including former references.
export function useRotationExit(choices: RotationChoice[], reset: (ids: number[]) => void, jobRunning: boolean, saving = false) {
  const [open, setOpen] = useState(false);
  const pending = useRef<(() => void) | null>(null);
  const bypass = useRef(false);
  const dirty = choices.some(x => x.turns !== 0);
  const requestLeave = (action: () => void) => {
    if (bypass.current) { action(); return; }
    if (saving) return;
    if (!dirty) { action(); return; }
    pending.current = action; setOpen(true);
  };
  useLayoutEffect(() => {
    if (!dirty && !saving) return;
    const location = window.location.pathname + window.location.search;
    const unload = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    const unguard = guardNavigation(() => {
      if (bypass.current) return true;
      const next = window.location.pathname + window.location.search;
      window.history.replaceState(null, "", location);
      pending.current = () => { bypass.current = true; navigate(next, true); };
      if (!saving) setOpen(true); return false;
    });
    window.addEventListener("beforeunload", unload);
    return () => { unguard(); window.removeEventListener("beforeunload", unload); };
  }, [dirty, choices, saving]);
  return { requestLeave, editor: open && <RotationEditor initial={choices.filter(x => x.turns !== 0)} jobRunning={jobRunning}
    onSaved={ids => { reset(ids); window.dispatchEvent(new Event("ns-review-changed")); }}
    onClose={() => { pending.current = null; setOpen(false); }}
    onDiscard={() => { reset(choices.map(x => x.photo_id)); setOpen(false); bypass.current = true; try { pending.current?.(); } finally { bypass.current = false; pending.current = null; } }} /> };
}
