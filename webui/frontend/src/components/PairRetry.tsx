import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, type PairRetryGroup, type PairRetryPreview } from "../api";
import { useJobFeed } from "../jobs";
import { pairFailureReason, plural } from "../format";
import { Modal } from "./ui/Modal";
import { ConfirmDialog } from "./Confirm";
import { FileLocations } from "./ui/FileLocations";
import { Pager } from "./Pager";

function deliveryStatus(state: "verified" | "incomplete" | "unknown") {
  return state === "verified" ? {text:"Verified at destination",tone:"ok" as const}
    : state === "incomplete" ? {text:"Delivery incomplete — file may be partial",tone:"warning" as const}
    : {text:"Delivery not confirmed — no recorded result",tone:"warning" as const};
}

// Keep the open task outside responsive panes: changing Inspector layout must not
// discard its confirmation or request identity. Every entry point shares this flow.
const RetryContext = createContext<((ids: number[]) => void) | null>(null);
export function PairRetryProvider({ children }: { children: ReactNode }) {
  const [ids,setIds] = useState<number[] | null>(null);
  return <RetryContext.Provider value={selected=>setIds([...selected])}>
    {children}
    {ids && <PairRetryDialog ids={ids} onClose={()=>setIds(null)} />}
  </RetryContext.Provider>;
}

export function PairRetryButton({ ids, count = 1 }: { ids: number[]; count?: number }) {
  const open = useContext(RetryContext);
  const { jobs } = useJobFeed();
  const jobRunning = jobs.active != null && jobs.active.presented_status !== "Interrupted";
  return <button className="photo-action" disabled={jobRunning} title={jobRunning ? "Wait for the running job to finish." : undefined}
    onClick={()=>open?.(ids)}>Retry photo/XMP transfers ({count})…</button>;
}

function PairRetryDialog({ ids, onClose }: { ids: number[]; onClose: () => void }) {
  const [preview,setPreview] = useState<PairRetryPreview | null>(null);
  const [error,setError] = useState("");
  const [revision,setRevision] = useState(0);
  const [page,setPage] = useState(1);
  const [choice,setChoice] = useState<PairRetryGroup | null>(null);
  const request = useRef<string | null>(null);
  const { jobs } = useJobFeed();
  const jobRunning = jobs.active != null && jobs.active.presented_status !== "Interrupted";
  const scope = JSON.stringify(ids);
  useEffect(()=>{
    let live=true;
    setPreview(null);setError("");setPage(1);
    api.pairRetryPreview(ids).then(p=>{if(live)setPreview(p);},e=>{if(live)setError(e.message);});
    return ()=>{live=false;};
  },[scope,revision]);
  if (choice) return <ConfirmDialog confirm={{
    title:`Retry ${choice.mode === "move" ? "Move" : "Copy"} for ${plural(choice.file_ids.length,"photo/XMP pair")}?`,
    action:choice.mode === "move" ? "Retry Move" : "Retry Copy", danger:choice.mode === "move",
    body:["Retry resumes only these recorded incomplete transfers. Fix the reported storage or access problem first. Existing output is verified before reuse; changed or missing files can still prevent completion.",
      choice.mode === "move" ? "Both destination files must verify before any remaining source files are removed. This resumes the original Move." : "This resumes the original Copy. Both source files stay in place."],
    run:async()=>{
      if(jobRunning) throw new Error("Wait for the running job to finish.");
      request.current ??= Array.from(crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,"0")).join("");
      const run=await api.retryPairs(choice,request.current);
      if(run.id == null) throw new Error("The retry was not confirmed. Try again with the same request.");
      window.dispatchEvent(new Event("ns-review-changed"));
      onClose();
    },
  }} onClose={()=>{setChoice(null);}} />;
  return <Modal label="Retry photo/XMP transfers" onClose={onClose}>
    <h2>Retry photo/XMP transfers</h2>
    <p>Resume these incomplete imports using their original destination and Copy or Move mode. Other selected photos are left alone.</p>
    {!preview && !error && <p role="status">Checking recorded transfers…</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {preview && <>
      <p>{plural(preview.items.length,"incomplete transfer")} in this selection.</p>
      {preview.items.slice((page-1)*20,page*20).map(item=><section className="info-section" key={item.issue_id}>
        <h3>{item.filename} · {item.mode === "move" ? "Move" : "Copy"}</h3>
        {item.failure_context ? <p className="warning"><strong>Failed step: {item.failure_context.stage}.</strong>{" "}
          {Array.from(new Set(item.failure_context.paths.map(path=>path.split("/").pop()))).join(", ")}</p>
          : <p className="muted">The earlier log does not say which file or step failed. Both files are listed below.</p>}
        <p>{pairFailureReason(item.summary)}</p>
        {item.blocked && <p className="warning">{item.blocked}</p>}
        <p className="muted">Destination paths show where the files should go. Statuses come from the last job, not a live check. Retry checks the files again.</p>
        <FileLocations
          source={[{label:"Photo",path:item.source}, {label:"XMP",path:item.sidecar_source}]}
          destination={[{label:"Photo",path:item.destination,status:deliveryStatus(item.delivery.photo)},
            {label:"XMP",path:item.sidecar_destination,status:deliveryStatus(item.delivery.xmp)}]} />
      </section>)}
      {preview.items.length > 20 && <Pager page={page} pages={Math.ceil(preview.items.length/20)} total={preview.items.length}
        pageSize={20} sizes={[20]} onPage={setPage} onPageSize={()=>{}} />}
      {preview.items.length === 0 && <p>No incomplete photo/XMP transfers remain in this selection.</p>}
    </>}
    <footer className="settings-actions">
      <button onClick={onClose}>Close</button>
      <button onClick={()=>{request.current=null;setRevision(n=>n+1);}}>Refresh list</button>
      {preview?.groups.map(group=><button key={group.mode} className={group.mode === "move" ? "danger" : "primary"}
        disabled={jobRunning} title={jobRunning ? "Wait for the running job to finish." : undefined}
        onClick={()=>{request.current=null;setChoice(group);}}>
        Retry {group.mode === "move" ? "Move" : "Copy"} ({group.file_ids.length})…
      </button>)}
    </footer>
  </Modal>;
}
