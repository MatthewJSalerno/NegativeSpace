import { DateEditor } from "./DateEditor";
import { MetadataSources } from "./MetadataSources";
import { PhotoMatches, type MatchView } from "./PhotoMatches";
import { MatchReviewDialog } from "./MatchReviewDialog";
import type { ComparisonState } from "../comparisonState";
import { useRotationSave } from "./RotationControls";
import { useRotationExit } from "./RotationEditor";
import { captureDateMessage } from "../photoDates";
import { FileIssues } from "./FileIssues";
import { follow } from "../nav";
import { SimilarityRecovery } from "./SimilarityRecovery";
import { ReviewPreview, DEFAULT_VIEW, type PreviewView } from "./ReviewPreview";
import { useEffect, useRef, useState } from "react";
import { api, type BrowseFilters, type PhotoDetail, type PhotoPage, type Sort, type Status, type MatchPage, type MetadataSourceView } from "../api";
import { Workspace } from "./ui/Workspace";
import { ReviewNote } from "./ReviewNote";
import { ConfirmDialog, transferConfirm, type Confirm } from "./Confirm";
import { useJobFeed } from "../jobs";

export function ReviewWorkspace({ initialPhoto, filters, sort, status, onBack, onPhoto, onEmpty }: {
  initialPhoto: number; filters: BrowseFilters; sort: Sort; status: Status;
  onBack: () => void; onPhoto: (id: number) => void; onEmpty: (message: string) => void;
}) {
  const [bookmark, setBookmark] = useState<{photo: number; reason: string | null} | null>(null);
  const [dateEdit, setDateEdit] = useState<{photo: number; donor?: MetadataSourceView} | null>(null);
  const [matchView, setMatchView] = useState<MatchView>({threshold: filters.match_min ?? 90, page: 1});
  const [comparison, setComparison] = useState<ComparisonState | null>(null);
  const dateEditButton = useRef<HTMLButtonElement>(null);
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
  const rotationSaver = useRotationSave((id, survivor) => {
    setViews(old => ({ ...old, [id]: { ...(old[id] ?? DEFAULT_VIEW), rotation: 0 } }));
    if (survivor != null) setNotice("Rotation saved. The existing photo was kept; both histories are preserved.");
    setRevision(n => n+1);
  });
  const rotationExit = useRotationExit(Object.entries(views).map(([id, view]) => ({photo_id:Number(id),turns:view.rotation/90})), ids => {
    setViews(old => Object.fromEntries(Object.entries(old).map(([id,view]) => [id,ids.includes(Number(id)) ? {...view,rotation:0} : view])));
    setRevision(n=>n+1);
  }, !!jobs.active, rotationSaver.busy);
  const scope = JSON.stringify(filters);
  const bookmarkReason = filters.reason === "later" && bookmark?.photo === photo?.id ? bookmark?.reason : null;
  // A date bookmark shows its reason, note and recorded dates first; the editor opens on request.
  useEffect(() => {
    if (photo && bookmarkReason === "date") dateEditButton.current?.focus();
  }, [photo?.id, bookmarkReason]);
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
  const title = filters.reason === "issues" ? "File verification" : filters.reason === "small" ? "Small-image review" : filters.reason === "later" ? "Bookmarked photos"
    : filters.suspicious ? "Suspicious-date review" : filters.undated ? "Missing-date review" : "Photo review";
  const matchLink = new URLSearchParams(window.location.search);
  matchLink.delete("review_photo");
  matchLink.delete("review");
  matchLink.delete("match_page");
  if (photo) matchLink.set("photo", String(photo.id));
  matchLink.set("tab", "similar"); matchLink.set("match", String(filters.match_min ?? 90));
  return <Workspace label="Review photos" title={title} subject={photo?.filename} onBack={() => rotationExit.requestLeave(onBack)} busy={busy || rotationSaver.busy} className="photo-review-workspace"
    step={{position: data?.total ? `Photo ${page} of ${data.total}` : "Review", previousLabel:"Previous photo",nextLabel:"Next photo",
      onPrevious:()=>rotationExit.requestLeave(()=>setPage(n=>Math.max(1,(n??1)-1))),onNext:()=>rotationExit.requestLeave(()=>setPage(n=>(n??1)+1)),previousDisabled:page==null||page<=1,nextDisabled:!data||page==null||page>=data.total}}
    status={<span role="status">{notice || "Next leaves this photo unresolved. Your gallery selection is unchanged."}{busy && " Saving or waiting for the job…"}</span>}>
    {error && <p className="error" role="alert">{error} {!error.startsWith("Only organized") && !error.startsWith("This photo is no longer") && !error.startsWith("This photo is outside") && <button onClick={()=>setRevision(n=>n+1)}>Retry loading</button>}</p>}
    {photo && <div className="review-photos">
      <ReviewPreview rotationSaver={rotationSaver} jobRunning={!!jobs.active} prominent label="Photo to review" photo={photo} view={views[photo.id] ?? DEFAULT_VIEW} onChange={v=>setViews(old=>({...old,[photo.id]:v}))} refreshKey={revision}/>
      <aside className="review-decision-panel" aria-label="Review decision">
        <FileIssues key={photo.id} photoId={photo.id} initialIssues={photo.issues ?? []} onResolved={()=>changed("File issue resolved.")} />
        <ReviewNote onBookmark={reason => setBookmark({photo:photo.id,reason})} key={photo.id} id={photo.id} refreshKey={revision} reason={filters.reason} disabled={!!jobs.active} onBusy={setBusy} onResolved={changed}
          concerns={photo.date_warning ? [{label:"Suspicious date",message:`${photo.date_taken ?? "Unknown date"}. ${photo.date_warning} To correct the date, open the photo’s Metadata tab.`}]
            : captureDateMessage(photo) ? [{label:"No usable capture date",message:captureDateMessage(photo)!}] : []}
          actions={["Completed","Copied","Found_At_Destination"].includes(photo.status) && <button disabled={busy||!!jobs.active} title={jobs.active ? "Wait for the running job to finish." : "Moves this photo to Rejects after confirmation."} onClick={()=>setConfirm(transferConfirm("reject",status,[photo.id],async()=>{
            const run=await api.startJob({mode:"reject",file_ids:[photo.id]});if (run.id == null) throw new Error("The Reject job was not accepted. Reload before trying again."); setRejectRun({run:run.id,photo:photo.id});setBusy(true);
          },undefined,photo.filename))}>Reject…</button>} />
        {(bookmarkReason === "date" || bookmarkReason === "details") && <section aria-label="Bookmark metadata">
          {bookmarkReason === "date" && <button ref={dateEditButton} disabled={!!jobs.active} title={jobs.active ? "Wait for the running job to finish." : undefined} onClick={() => setDateEdit({photo:photo.id})}>Edit metadata date…</button>}
          <MetadataSources photoId={photo.id} refreshKey={revision} editable jobRunning={!!jobs.active} onEdit={donor => setDateEdit({photo:photo.id,donor})} />
        </section>}
        {bookmarkReason === "compare" && <PhotoMatches key={photo.id} id={photo.id} name={photo.filename} delivered view={matchView} onView={setMatchView}
          refreshKey={revision} changes={revision} jobRunning={!!jobs.active} onReview={(candidate, scope = "library", page = 1) => rotationExit.requestLeave(() => setComparison({
            origin:photo.id,reference:photo.id,candidate,scope,threshold:matchView?.threshold ?? 90,page,views:{},linked:false,share:72,
          }))} />}
        {matches && bookmarkReason !== "compare" && <section className="review-evidence" aria-label="Similar photos"><h3>Similar photos</h3>
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
    {dateEdit != null && <DateEditor photoId={dateEdit.photo} donor={dateEdit.donor} onClose={() => setDateEdit(null)} onSaved={() => { setRevision(n=>n+1); window.dispatchEvent(new Event("ns-review-changed")); }} />}
    {comparison && <MatchReviewDialog reference={comparison.reference} candidate={comparison.candidate} workspace={comparison} onWorkspace={setComparison}
      initialView={{threshold:comparison.threshold,page:comparison.page}} onView={setMatchView} jobRunning={!!jobs.active}
      onClose={() => setComparison(null)} onChanged={() => setRevision(n=>n+1)} />}
    {rotationExit.editor}
    {confirm && <ConfirmDialog confirm={confirm} onClose={()=>setConfirm(null)}/>}
  </Workspace>;
}
