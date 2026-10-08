import { Thumb } from "./Thumb";
import { SimilarityRecovery } from "./SimilarityRecovery";
import { MatchReviewDialog } from "./MatchReviewDialog";
import type { ComparisonState } from "../comparisonState";
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
  const [comparison, setComparison] = useState<ComparisonState | null>(null);
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
    api.inspect(initialPhoto).then(detail => {
      if (!["Completed", "Copied", "Found_At_Destination"].includes(detail.status)) throw new Error("Only organized photos in Library can be reviewed. Return to the gallery for file information.");
      return api.photoPosition({ ...filters, sort, page_size:1, photo_id:initialPhoto });
    }).then(p => { if(live) { if(p.page == null) setError("This photo is outside the current filters. Return to the gallery to choose a photo in this view."); else setPage(p.page); } }, e => { if(live) setError(e.message); });
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
      if (!["Completed", "Copied", "Found_At_Destination"].includes(detail.status)) throw new Error("This photo is no longer in Library. Return to the gallery to refresh the review queue.");
      setPhoto(detail); onPhoto(item.id);
      if (["Completed", "Copied", "Found_At_Destination"].includes(detail.status)) {
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
  const title = filters.reason === "small" ? "Small-image review" : filters.reason === "later" ? "Review later"
    : filters.suspicious ? "Suspicious-date review" : filters.undated ? "Missing-date review" : "Photo review";
  const evidence = matches ? [...(larger ? [larger] : []), ...matches.items.filter(p => p.id !== larger?.id)].slice(0, 3) : [];
  return <Workspace label="Review photos" title={title} subject={photo?.filename} onBack={onBack} busy={busy || comparison != null} className="photo-review-workspace"
    step={{position: data?.total ? `Photo ${page} of ${data.total}` : "Review", previousLabel:"Previous photo",nextLabel:"Next photo",
      onPrevious:()=>setPage(n=>Math.max(1,(n??1)-1)),onNext:()=>setPage(n=>(n??1)+1),previousDisabled:page==null||page<=1,nextDisabled:!data||page==null||page>=data.total}}
    status={<span role="status">{notice || "Next leaves this photo unresolved. Your gallery selection is unchanged."}{busy && " Saving or waiting for the job…"}</span>}>
    {error && <p className="error" role="alert">{error} {!error.startsWith("Only organized") && !error.startsWith("This photo is no longer") && !error.startsWith("This photo is outside") && <button onClick={()=>setRevision(n=>n+1)}>Retry loading</button>}</p>}
    {photo && <div className="review-photos">
      <ReviewPreview prominent label="Photo to review" photo={photo} view={views[photo.id] ?? DEFAULT_VIEW} onChange={v=>setViews(old=>({...old,[photo.id]:v}))} refreshKey={revision}/>
      <aside className="review-decision-panel" aria-label="Review decision">
        <ReviewNote key={photo.id} id={photo.id} refreshKey={revision} reason={filters.reason} disabled={!!jobs.active} onBusy={setBusy} onResolved={changed}
          concerns={photo.date_warning ? [{label:"Suspicious date",message:`${photo.date_taken ?? "Unknown date"}. ${photo.date_warning} Date editing is not available yet.`}]
            : !photo.exif_dates?.some(d => d.field === "taken") ? [{label:"No capture date",message:"No date taken is recorded in the photo’s EXIF. Date editing is not available yet."}] : []}
          actions={["Completed","Copied","Found_At_Destination"].includes(photo.status) && <button disabled={busy||!!jobs.active} title={jobs.active ? "Wait for the running job to finish." : "Moves this photo to Rejects after confirmation."} onClick={()=>setConfirm(transferConfirm("reject",status,[photo.id],async()=>{
            const run=await api.startJob({mode:"reject",file_ids:[photo.id]});if (run.id == null) throw new Error("The Reject job was not accepted. Reload before trying again."); setRejectRun({run:run.id,photo:photo.id});setBusy(true);
          },undefined,photo.filename))}>Reject…</button>} />
        {matches && <section className="review-evidence" aria-label="Similar-photo clues"><h3>Similar-photo clues</h3>
          <p className="section-note">{matches.availability !== "available" ? "Visual matching is unavailable for this photo."
            : matches.total === 0 ? `No recorded matches at ${filters.match_min ?? 90}% or higher.`
            : `${matches.total} potential matches at ${filters.match_min ?? 90}% or higher. Compare before deciding.`}</p>
          {evidence.length > 0 && <ul className="review-evidence-list">{evidence.map(item => <li key={item.id}>
            <button className="inspector-match" disabled={busy} aria-label={`Review side by side: ${item.filename}`}
              onClick={() => setComparison({origin:photo.id,reference:photo.id,candidate:item.id,threshold:filters.match_min??90,page:1,views:{},linked:false,share:72})}>
              <Thumb id={item.id} alt="" refreshKey={revision}/><span><strong>{item.filename}</strong>
                <span>{item.width && item.height ? `${item.width} × ${item.height}` : "Dimensions unknown"}{larger?.id===item.id ? " · Larger image" : ""}</span>
                <span>Review side by side</span></span>
            </button></li>)}</ul>}
          {(matches.availability !== "available" || matches.state.pending > 0 || matches.state.unavailable > 0) && <>
            <p className="section-note">Matching is incomplete; other copies may exist.</p>
            <SimilarityRecovery photoId={matches.availability === "hash_unavailable" ? photo.id : undefined} onRecovered={() => setRevision(n=>n+1)}/>
          </>}
        </section>}
      </aside>
    </div>}
    {!photo && !error && (data ? <p>No more photos at this position. Earlier skipped photos may still need review. Use Previous or return to the gallery.</p> : <p role="status">Loading review…</p>)}
    {comparison && <MatchReviewDialog returnTo="review" reference={comparison.origin} candidate={comparison.candidate} workspace={comparison} onWorkspace={setComparison}
      initialView={{threshold:comparison.threshold,page:comparison.page}} onView={() => undefined} jobRunning={!!jobs.active}
      onClose={() => {setComparison(null);setRevision(n=>n+1);}} onChanged={() => setRevision(n=>n+1)} />}
    {confirm && <ConfirmDialog confirm={confirm} onClose={()=>setConfirm(null)}/>}
  </Workspace>;
}
