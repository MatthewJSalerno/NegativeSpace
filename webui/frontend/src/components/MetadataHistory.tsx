import { useEffect, useState, type MouseEvent } from "react";
import { api, type LogFilters, type MetadataHistoryPage } from "../api";
import { instant, plural } from "../format";
import { follow, logUrl, photoUrl } from "../nav";
import { jobLabel } from "../jobs";
import { Pager } from "./Pager";
import { MetadataChoiceComparison } from "./MetadataChoiceComparison";

const sourceName=(id:string|null)=>id==="exif" ? "EXIF" : id==="embedded_xmp" ? "Embedded XMP" : id?.replace(/^sidecar:/,"") ?? "Not recorded";

// One history presentation for Logs and lineage. Saving never implies file delivery.
export function MetadataHistory({filters,refreshKey=0,onNavigate}: {filters:LogFilters;refreshKey?:number;onNavigate?:()=>void}) {
  const [open,setOpen]=useState(false);
  const [comparison,setComparison]=useState<{photoId:number;revision:number}|null>(null);
  const scope=JSON.stringify(filters);
  const [position,setPosition]=useState({scope,page:1});
  const page=position.scope===scope ? position.page : 1;
  const setPage=(page:number)=>setPosition({scope,page});
  const [size,setSize]=useState(20);
  const [data,setData]=useState<MetadataHistoryPage|null>(null);
  const [error,setError]=useState("");
  const [retry,setRetry]=useState(0);
  const [loading,setLoading]=useState(false);
  useEffect(()=>{setData(null);setError("");setComparison(null);},[scope]);
  useEffect(()=>{
    if(!open)return;
    let live=true;setLoading(true);setError("");
    api.metadataHistory(JSON.parse(scope),page,size).then(d=>{if(live){setData(d);setLoading(false);}},e=>{if(live){setError(e.message);setLoading(false);}});
    return()=>{live=false;};
  },[scope,page,size,open,refreshKey,retry]);
  const go=(e:MouseEvent<HTMLAnchorElement>)=>{
    if(e.button===0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey)onNavigate?.();
    follow(e);
  };
  return <><details open={open} onToggle={e=>setOpen(e.currentTarget.open)} className="metadata-history">
    <summary><strong>Metadata choices</strong><span className="section-note">Saved and applied import decisions</span></summary>
    <div className="message-copy">
    <p className="section-note">Saved choices do not change files. Applied entries link to the job that used them. Job counts and exports cover file operations separately.</p>
    {(filters.run.length>0 || filters.status.length>0) && <p className="section-note">Job and status filters show applied entries only. Clear those filters to see saved choices.</p>}
    {loading && <p role="status">Loading metadata history…</p>}
    {error && <p className="error" role="alert">{error} <button className="link" onClick={()=>setRetry(n=>n+1)}>Retry history</button></p>}
    {data && !error && <>
      <p className="section-note">{plural(data.total,"metadata entry","metadata entries")}</p>
      {!data.total && !loading && <p>No metadata choices match these filters.</p>}
      <ol className="history-list" aria-label="Metadata choice entries" aria-busy={loading}>
        {data.items.map(item=><li key={item.id} className="message-copy">
          <div><strong>{item.stage==="applied" ? "Applied metadata during import" : item.kind==="association" ? "Saved XMP ownership" : "Saved primary for import"}</strong>
          <span className="muted"> · {instant(item.timestamp)}</span></div>
          <p>{item.photo_id!=null ? <a href={photoUrl(item.photo_id)} onClick={go}>{item.filename}</a> : item.filename}</p>
          {item.kind==="association" ? <><p>Sidecar: <code>{item.sidecar}</code></p><dl><dt>Use for</dt>{item.owners.map(name=><dd key={name}>{name}</dd>)}</dl></>
            : <><p>Primary: <code>{sourceName(item.primary)}</code></p><p>Date taken: {item.date_taken==="" ? "Empty" : item.date_taken ?? "Not recorded"}</p></>}
          {item.stage==="saved" ? <p className="section-note">Choice #{item.revision} saved. No files changed.</p>
            : <p>{item.applied_choices.length ? <>Used {item.applied_choices.length===1 ? "choice" : "choices"} {item.applied_choices.map(n=>`#${n}`).join(", ")}. </> : null}<a href={logUrl({run:item.run_id!,photo:item.photo_id ?? undefined})} onClick={go}>{jobLabel(item.run_id!,item.mode)}</a></p>}
          {item.stage==="saved" && item.revision!=null && (filters.photo ?? item.photo_id)!=null &&
            <button className="link" onClick={()=>setComparison({photoId:(filters.photo ?? item.photo_id)!,revision:item.revision!})}>Compare metadata…</button>}
        </li>)}
      </ol>
      {data.total>size && <Pager page={page} pages={Math.max(1,Math.ceil(data.total/size))} total={data.total} pageSize={size}
        onPage={setPage} onPageSize={n=>{setSize(n);setPage(1);}} sizes={[20,50,100]} noun="entry" nouns="entries" />}
    </>}
    </div>
  </details>
  {comparison && <MetadataChoiceComparison {...comparison} onClose={()=>setComparison(null)} />}
  </>;
}
