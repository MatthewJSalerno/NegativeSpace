import { useEffect, useState } from "react";
import { api, type MetadataChoiceComparison as Comparison } from "../api";
import { instant } from "../format";
import { Modal } from "./ui/Modal";
import { MetadataFieldTable } from "./MetadataFieldTable";
import { own, stable, comparable } from "./metadataFields";

export function MetadataChoiceComparison({photoId,revision,onClose}: {photoId:number;revision:number;onClose:()=>void}) {
  const [data,setData]=useState<Comparison|null>(null);
  const [error,setError]=useState("");
  const [retry,setRetry]=useState(0);
  const [differences,setDifferences]=useState(false);
  useEffect(()=>{
    let live=true;setData(null);setError("");
    api.metadataChoiceComparison(photoId,revision).then(d=>{if(live)setData(d);},e=>{if(live)setError(e.message);});
    return()=>{live=false;};
  },[photoId,revision,retry]);
  const primary=data?.primary?.available ? data.primary : null;
  const source=data?.historical;
  const fields=[...new Set(["date_taken",...Object.keys(source?.fields ?? {}),...Object.keys(primary?.fields ?? {})])]
    .sort((a,b)=>a==="date_taken" ? -1 : b==="date_taken" ? 1 : a.localeCompare(b));
  const shown=fields.filter(k=>!differences || !primary || !source
    || own(source.fields,k)!==own(primary.fields,k)
    || stable(comparable(source.fields[k],k))!==stable(comparable(primary.fields[k],k)));
  return <Modal label="Compare saved metadata" onClose={onClose}>
    <h2>Compare saved metadata</h2>
    {!data && !error && <p role="status">Loading comparison…</p>}
    {error && <p className="error" role="alert">{error} <button className="link" onClick={()=>setRetry(n=>n+1)}>Retry comparison</button></p>}
    {data && <>
      <h3>{data.filename}</h3>
      <p>Choice #{data.revision} · Saved {instant(data.saved_at)}</p>
      <p>Recorded XMP: <code>{data.historical.label}</code></p>
      {data.assigned_to_photo !== null && <p>{data.assigned_to_photo ? "Assigned to" : "Assigned only to"} {data.owners.join(", ")}.{!data.assigned_to_photo && " This choice did not apply the XMP to this photo."}</p>}
      <p className="section-note">Compare the XMP recorded with this choice against the photo’s current recorded primary. Viewing does not change ownership, metadata or files. Shared filenames do not establish that photos show the same image.</p>
      {data.issues.map((issue,i)=><p className="notice" key={i}>{issue.detail || issue.code.replaceAll("_"," ")}</p>)}
      {!primary && <p className="notice">No current primary metadata is available for comparison. {data.notice}</p>}
      {!source?.available ? <p className="notice">The metadata fields for this saved choice are unavailable.</p> : <>
        {primary && <label className="checkbox-row"><input type="checkbox" checked={differences} onChange={e=>setDifferences(e.target.checked)}/>Show differences only</label>}
        <div className="metadata-compare"><MetadataFieldTable caption="Saved choice comparison" fields={shown}
          source={source.fields} primary={primary?.fields} primaryLabel={`Current primary · ${primary?.label ?? ""}`}
          sourceLabel="Recorded XMP · Saved choice" /></div>
        {!shown.length && <p>No differing fields.</p>}
      </>}
    </>}
    <div className="settings-actions"><button onClick={onClose}>Close</button></div>
  </Modal>;
}
