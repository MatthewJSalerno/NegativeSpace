import { follow } from "../nav";
import { SimilarityRecovery } from "./SimilarityRecovery";
import { ReviewPreview, DEFAULT_VIEW, type PreviewView } from "./ReviewPreview";
import { useEffect, useState } from "react";
import { api, type BrowseFilters, type PhotoDetail, type PhotoPage, type Sort, type Status, type MatchPage } from "../api";
import { Workspace } from "./ui/Workspace";
import { ReviewNote } from "./ReviewNote";
import { ConfirmDialog, transferConfirm, type Confirm } from "./Confirm";
import { useJobFeed } from "../jobs";

export function ReviewWorkspace({ initialPhoto, filters, sort, status, onBack, onPhoto, onEmpty }: {
  initialPhoto: number; filters: BrowseFilters; sort: Sort; status: Status;
  onBack: () => void; onPhoto: (id: number) => void; onEmpty: (message: string) => void;
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
      if (result.total === 0) {
        onEmpty(`${notice ? `${notice} ` : ""}No photos remain in this review.`);
        return;
      }
      const item=result.items[0];
      if(!item) return;
      const detail = await api.inspect(item.id);
      if(!live) return;
      if (!["Completed", "Copied", "Found_At_Destination"].includes(detail.status)) throw new Error("This photo is no longer in Library. Return to the gallery to refresh the review queue.");
      setPhoto(detail); onPhoto(item.id);
      if (["Completed", "Copied", "Found_At_Destination"].includes(detail.status)) {
        const related = await api.matches(new URLSearchParams({threshold:String(filters.match_min ?? 90),page_size:"1"}), item.id);
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
  const changed = (message: string) => {setNotice(message); setRevision(n=>n+1);};
  const title = filters.reason === "small" ? "Small-image review" : filters.reason === "later" ? "Review later"
    : filters.suspicious ? "Suspicious-date review" : filters.undated ? "Missing-date review" : "Photo review";
  const matchLink = new URLSearchParams(window.location.search);
  matchLink.delete("review_photo");
  matchLink.delete("review");
  matchLink.delete("match_page");
  if (photo) matchLink.set("photo", String(photo.id));
  matchLink.set("tab", "similar"); matchLink.set("match", String(filters.match_min ?? 90));
  return <Workspace label="Review photos" title={title} subject={photo?.filename} onBack={onBack} busy={busy} className="photo-review-workspace"
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
        {matches && <section className="review-evidence" aria-label="Similar photos"><h3>Similar photos</h3>
          <p className="section-note">{matches.availability !== "available" ? "Visual matching is unavailable for this photo."
            : matches.total === 0 ? `No recorded matches at ${filters.match_min ?? 90}% or higher.`
            : `${matches.total} potential matches at ${filters.match_min ?? 90}% or higher.`}</p>
          {matches.total > 0 && <p><a href={`/?${matchLink}`} aria-disabled={busy || undefined}
            onClick={event => { if (busy) event.preventDefault(); else follow(event); }}>View all {matches.total} matches →</a></p>}
          {(matches.availability !== "available" || matches.state.pending > 0 || matches.state.unavailable > 0) && <>
            <p className="section-note">Matching is incomplete; other copies may exist.</p>
            <SimilarityRecovery photoId={matches.availability === "hash_unavailable" ? photo.id : undefined} onRecovered={() => setRevision(n=>n+1)}/>
          </>}
        </section>}
      </aside>
    </div>}
    {!photo && !error && (data ? <p>No more photos at this position. Earlier skipped photos may still need review. Use Previous or return to the gallery.</p> : <p role="status">Loading review…</p>)}
    {confirm && <ConfirmDialog confirm={confirm} onClose={()=>setConfirm(null)}/>}
  </Workspace>;
}
