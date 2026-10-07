import { ReviewPreview, DEFAULT_VIEW, type PreviewView } from "./ReviewPreview";
import { useEffect, useState } from "react";
import { api, type BrowseFilters, type PhotoDetail, type PhotoPage, type Sort, type Status, type MatchPage } from "../api";
import { Workspace } from "./ui/Workspace";
import { ReviewNote } from "./ReviewNote";
import { ConfirmDialog, transferConfirm, type Confirm } from "./Confirm";
import { useJobFeed } from "../jobs";

export function ReviewWorkspace({ initialPhoto, filters, sort, status, onBack, onPhoto }: {
  initialPhoto: number; filters: BrowseFilters; sort: Sort; status: Status;
  onBack: () => void; onPhoto: (id: number) => void;
}) {
  const [page, setPage] = useState<number | null>(null);
  const [data, setData] = useState<PhotoPage | null>(null);
  const [photo, setPhoto] = useState<PhotoDetail | null>(null);
  const [views, setViews] = useState<Record<number, PreviewView>>({});
  const [matches, setMatches] = useState<MatchPage | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [rejectRun, setRejectRun] = useState<{run: number; photo: number} | null>(null);
  const { jobs } = useJobFeed();
  const scope = JSON.stringify(filters);
  useEffect(() => {
    const update = () => setRevision(n=>n+1);
    window.addEventListener("ns-settings-saved",update);
    return ()=>window.removeEventListener("ns-settings-saved",update);
  }, []);
  useEffect(() => {
    let live=true;
    api.photoPosition({ ...filters, sort, page_size:1, photo_id:initialPhoto }).then(p => { if(live) setPage(p.page ?? 1); }, e => { if(live) setError(e.message); });
    return () => {live=false;};
  }, []);
  useEffect(() => {
    if (page == null) return;
    let live=true;
    setPhoto(null); setData(null); setMatches(null); setError("");
    api.photos({ ...filters, sort, page, page_size:1 }).then(async result => {
      if(!live) return;
      setData(result);
      const item=result.items[0];
      if(!item) return;
      const detail = await api.inspect(item.id);
      if(!live) return;
      setPhoto(detail); onPhoto(item.id);
      if (filters.reason === "small" || item.review?.reasons.some(n=>n.reason==="small")) {
        const related = await api.matches(new URLSearchParams({threshold:String(filters.match_min ?? 90),page_size:"60"}), item.id);
        if(live) setMatches(related);
      }
    }).catch(e=>{if(live)setError(e.message);});
    return ()=>{live=false;};
  }, [page, revision, scope, sort]);
  useEffect(() => {
    if(rejectRun == null || jobs.last?.id !== rejectRun.run || jobs.active) return;
    let live=true;
    api.inspect(rejectRun.photo).then(p=>{
      if(!live)return;
      setRejectRun(null); setBusy(false);
      if (["Rejected","Rejected_Copied"].includes(p.status)) {setNotice("Photo moved to Rejects."); setRevision(n=>n+1); window.dispatchEvent(new Event("ns-review-changed"));}
      else setError("The photo was not rejected. Check the job’s outcome before trying again.");
    }).catch(e=>{if(live){setError(e.message);setRejectRun(null);setBusy(false);}});
    return ()=>{live=false;};
  }, [rejectRun, jobs.last?.id, jobs.active]);
  const candidate = matches?.largest_match;
  const larger = candidate && (candidate.width ?? 0)*(candidate.height ?? 0) > (photo?.width ?? 0)*(photo?.height ?? 0) ? candidate : null;
  const changed = (message: string) => {setNotice(message); setRevision(n=>n+1);};
  return <Workspace label="Review photos" title="Needs review" subject={photo?.filename} onBack={onBack} busy={busy}
    step={{position: data?.total ? `Photo ${page} of ${data.total}` : "Review", previousLabel:"Previous photo",nextLabel:"Next photo",
      onPrevious:()=>setPage(n=>Math.max(1,(n??1)-1)),onNext:()=>setPage(n=>(n??1)+1),previousDisabled:page==null||page<=1,nextDisabled:!data||page==null||page>=data.total}}
    status={<span role="status">{notice || "Next leaves this photo unresolved. Your gallery selection is unchanged."}{busy && " Saving or waiting for the job…"}</span>}>
    {error && <p className="error" role="alert">{error} <button onClick={()=>setRevision(n=>n+1)}>Retry loading</button></p>}
    {photo && <div className="review-photos"><section>
      <ReviewPreview label="Photo to review" photo={photo} view={views[photo.id] ?? DEFAULT_VIEW} onChange={v=>setViews(old=>({...old,[photo.id]:v}))} refreshKey={revision}/>
      <ReviewNote key={photo.id} id={photo.id} refreshKey={revision} reason={filters.reason} disabled={!!jobs.active} onBusy={setBusy} onResolved={changed}/>
      {["Completed","Copied","Found_At_Destination"].includes(photo.status) && <button disabled={busy||!!jobs.active} title={jobs.active ? "Wait for the running job to finish." : undefined} onClick={()=>setConfirm(transferConfirm("reject",status,[photo.id],async()=>{
        const run=await api.startJob({mode:"reject",file_ids:[photo.id]});if (run.id == null) throw new Error("The Reject job was not accepted. Reload before trying again."); setRejectRun({run:run.id,photo:photo.id});setBusy(true);
      },undefined,photo.filename))}>Reject…</button>}
    </section>{matches && <section><h3>Look-alike evidence</h3><p>{matches.availability === "available" ? `${matches.total} recorded look-alikes at ${filters.match_min ?? 90}% or higher.` : "Matching evidence is unavailable for this photo. It may lack a usable visual hash."}</p>
      {larger ? <><ReviewPreview label="Larger look-alike" photo={larger} view={views[larger.id] ?? DEFAULT_VIEW} onChange={v=>setViews(old=>({...old,[larger.id]:v}))} refreshKey={revision}/><p>Location: Library. This larger look-alike is evidence, not a recommendation to reject.</p></> : <p>No larger look-alike in the available matching evidence. Small size alone does not make a photo unwanted.</p>}
      {(matches.state.pending > 0 || matches.state.unavailable > 0) && <p>Matching coverage is incomplete. Missing evidence does not establish that this is the only copy.</p>}
    </section>}</div>}
    {!photo && !error && (data ? <p>No more photos at this position. Earlier skipped photos may still need review. Use Previous or return to the gallery.</p> : <p role="status">Loading review…</p>)}
    {confirm && <ConfirmDialog confirm={confirm} onClose={()=>setConfirm(null)}/>}
  </Workspace>;
}
