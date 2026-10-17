import { useEffect, useState } from "react";
import { api, type ImportChoice, type ImportChoiceContext, type ImportChoicePreview } from "../api";
import { useJobFeed } from "../jobs";
import { Modal } from "./ui/Modal";

const display = (value: unknown) => value === "" ? "Empty" : value == null ? "Not recorded" : typeof value === "string" ? value : JSON.stringify(value);
const label = (id: string) => id === "exif" ? "EXIF" : id === "embedded_xmp" ? "Embedded XMP" : id.replace(/^sidecar:/, "");

export function ImportChoiceDialog({photoId,onClose}: {photoId:number;onClose:()=>void}) {
  const [data,setData]=useState<ImportChoiceContext | null>(null);
  const [owners,setOwners]=useState<number[]>([]);
  const [primary,setPrimary]=useState("");
  const [editingSide,setEditingSide]=useState("");
  const [editingPrimary,setEditingPrimary]=useState(false);
  const [preview,setPreview]=useState<ImportChoicePreview | null>(null);
  const [requestId,setRequestId]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  const {jobs}=useJobFeed();
  const reload=async()=>{
    const next=await api.importChoices(photoId);
    setData(next);setOwners([]);setPrimary("");setEditingSide("");setEditingPrimary(false);setPreview(null);setRequestId("");
  };
  useEffect(()=>{let live=true;api.importChoices(photoId).then(d=>{if(live)setData(d);},e=>{if(live)setError(e.message);});return()=>{live=false;};},[photoId]);
  const side=data?.sidecars.find(s=>s.path===editingSide || s.needs_choice);
  const blocked=!!data?.blockers.length || !!side?.candidates.some(c=>!c.selectable);
  const needsPrimary=!!data?.needs_primary && (!data.primary_id || editingPrimary);
  const complete=!!data && !side && !blocked && !needsPrimary;
  const savedSource=data?.sources.find(s=>s.id===data.primary_id);
  const choose=async()=>{
    if(!data)return;
    const choice:ImportChoice={photo_id:photoId,kind:side ? "association" : "primary",
      selection:side ? {capture_id:data.capture_id,sidecar:side.path,owner_ids:owners} : {capture_id:data.capture_id,primary_id:primary}};
    setBusy(true);setError("");setMessage("");
    try {setPreview(await api.previewImportChoice(photoId,choice));setRequestId(Array.from(crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,"0")).join(""));}
    catch(e){setError(e instanceof Error ? e.message : "Unable to preview this choice.");}
    finally{setBusy(false);}
  };
  const save=async()=>{
    if(!preview)return;
    setBusy(true);setError("");
    try {
      const result=await api.confirmImportChoice(photoId,preview,requestId);
      setMessage(result.message);setPreview(null);
      await reload();
      window.dispatchEvent(new Event("ns-review-changed"));
    } catch(e){setError(e instanceof Error ? e.message : "The choice was not confirmed. Retry this confirmation.");}
    finally{setBusy(false);}
  };
  return <Modal label="Resolve XMP import choices" onClose={onClose} busy={busy}>
    <h2>{preview ? "Confirm import choice" : complete ? "XMP choices saved" : "Resolve XMP import choices"}</h2>
    {data && <p><strong>{data.filename}</strong> · Not organized</p>}
    <p>These choices apply when you Copy or Move. Saving here does not change or remove source files.</p>
    {message && <p role="status">{message}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {jobs.active && <p className="notice">A job is running. Wait for it to finish before saving a choice.</p>}
    {!data && !error && <p role="status">Loading recorded metadata…</p>}
    {data && !preview && <>
      {data.sidecars.filter(s=>s.saved && s.can_choose && s.path!==side?.path).map(s=><section key={s.path}>
        <h3>Saved ownership</h3><p><code>{s.path}</code></p>
        <ul>{s.candidates.filter(c=>c.file_id!=null && s.owner_ids.includes(c.file_id)).map(c=><li key={c.path}>{c.path}</li>)}</ul>
        {s.can_choose && <button className="photo-action" disabled={busy || !!jobs.active} onClick={()=>{setEditingSide(s.path);setOwners(s.owner_ids);setMessage("");}}>Change owners…</button>}
      </section>)}
      {blocked ? <p className="notice">Some source evidence is unreadable, unindexed, or already organized. Check the photo's recorded issues and run Index after repairing the source. This choice cannot be saved yet.</p>
      : side ? <>
        <h3>Which photos belong to this XMP?</h3>
        <p>Source sidecar: <code>{side.path}</code></p>
        <p>Choose one or more photos. Other candidates will not use this sidecar.</p>
        <fieldset disabled={busy}><legend>Photos (required)</legend>
          {side.candidates.map(c=><label className="checkbox-row" key={c.path}>
            <input type="checkbox" checked={owners.includes(c.file_id!)} onChange={e=>setOwners(old=>e.target.checked ? [...old,c.file_id!] : old.filter(id=>id!==c.file_id))}/>
            <span>{c.path}</span></label>)}
        </fieldset>
        <details><summary>Recorded sidecar fields</summary><table className="review-metadata-table"><tbody>
          {Object.entries(side.fields).map(([key,value])=><tr key={key}><th>{key === "date_taken" ? "Date taken" : key.replaceAll("_"," ")}</th><td>{display(value)}</td></tr>)}
        </tbody></table></details>
      </> : needsPrimary ? <>
        <h3>Which XMP version should be primary?</h3>
        <p>All captured versions are preserved. The primary supplies metadata for filing and future edits. Missing fields may fall back; explicitly empty fields stay empty.</p>
        {data.primary_id && <p>Saved choice: <strong>{label(data.primary_id)}</strong>. Copy or Move will apply it.</p>}
        <fieldset disabled={busy}><legend>Metadata source (required)</legend>
          {data.sources.filter(s=>s.id.startsWith("sidecar:")).map(s=><label className="checkbox-row" key={s.id}><input type="radio" name="import-primary" value={s.id} checked={primary===s.id} onChange={()=>setPrimary(s.id)}/>
            <span>{s.label} — Date taken: {display(s.fields.date_taken)}</span></label>)}
        </fieldset>
        <details><summary>Compare recorded fields</summary><div className="metadata-compare"><table className="review-metadata-table"><thead><tr><th>Field</th>{data.sources.map(s=><th key={s.id}>{s.label}</th>)}</tr></thead><tbody>
          {[...new Set(data.sources.flatMap(s=>Object.keys(s.fields)))].sort().map(key=><tr key={key}><th>{key === "date_taken" ? "Date taken" : key.replaceAll("_"," ")}</th>{data.sources.map(s=><td key={s.id}>{display(s.fields[key])}</td>)}</tr>)}
        </tbody></table></div></details>
      </> : <>
        {data.needs_primary && data.primary_id && <section aria-label="Saved XMP version">
          <h3>Saved primary for import</h3>
          <p><strong>{label(data.primary_id)}</strong></p>
          <p>Date taken: <strong>{display(savedSource?.fields.date_taken)}</strong></p>
          <button className="photo-action" disabled={busy || !!jobs.active} onClick={()=>{setEditingPrimary(true);setPrimary(data.primary_id!);setMessage("");}}>Change XMP version…</button>
        </section>}
        <p>Next, Copy or Move to organize the photos using your saved choices.</p>
      </>}
    </>}
    {preview && <>
      {preview.choice.kind==="association" ? <><p>Source sidecar: <code>{preview.choice.selection.sidecar}</code></p><h3>Use this sidecar for</h3><ul>{preview.owners.map(path=><li key={path}>{path}</li>)}</ul><p>Other matching photos will not use this sidecar. The preference in Settings stays unchanged.</p></>
      : <><p>Primary: <strong>{label(preview.primary_id!)}</strong></p><p>Filing Date taken: <strong>{display(preview.effective?.date_taken)}</strong>. A missing, empty or partial date uses Undated filing.</p>
        <table className="review-metadata-table"><thead><tr><th>Field</th><th>Before</th><th>After</th></tr></thead><tbody>
          {preview.differences.map(d=><tr key={d.field}><th>{d.field === "date_taken" ? "Date taken" : d.field.replaceAll("_"," ")}</th><td>{d.before.present ? display(d.before.value) : "Not recorded"}</td><td>{d.after.present ? display(d.after.value) : "Not recorded"}</td></tr>)}
        </tbody></table><p>Copy/Move verifies the files and determines the available destination filename. No files move now.</p></>}
    </>}
    <div className="settings-actions">
      <button disabled={busy} onClick={onClose}>{message || complete ? "Close" : "Decide later"}</button>
      {error && <button disabled={busy} onClick={()=>void reload().then(()=>setError(""),e=>setError(e.message))}>Reload choices</button>}
      {preview ? <><button disabled={busy} onClick={()=>{setPreview(null);setError("");}}>Back</button><button className="primary" disabled={busy || !!jobs.active} onClick={()=>void save()}>{busy ? "Saving…" : "Save choice"}</button></>
        : data && !blocked && (side || needsPrimary) && <button className="primary" disabled={busy || !!jobs.active || (side ? !owners.length : !primary)} onClick={()=>void choose()}>Preview choice</button>}
    </div>
  </Modal>;
}
