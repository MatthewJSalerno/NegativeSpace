import { ReviewActions, type SetActions } from "./ReviewActions";
import type { ComparisonState } from "../comparisonState";
import { SimilarityRecovery } from "./SimilarityRecovery";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { api, MATCH_THRESHOLDS, type MatchPage, type MatchPhoto, type MatchReview, type MatchVerdict } from "../api";
import { moved, runAndWait } from "../rejecting";
import { RejectConfirm } from "./RejectConfirm";
import { count, instant } from "../format";
import { Thumb } from "./Thumb";
import { Workspace } from "./ui/Workspace";
import { ReviewPreview, DEFAULT_VIEW, type PreviewView } from "./ReviewPreview";
import { ReviewMetadata } from "./ReviewMetadata";

const VERDICTS: [MatchVerdict, string][] = [
  ["same", "Same photograph"], ["related", "Related photograph"], ["unrelated", "Unrelated"],
];
const verdictName = (value: MatchVerdict | null | undefined) => VERDICTS.find(([key]) => key === value)?.[1] ?? "Unreviewed";
const PAGE_SIZE = 12;

export function MatchReviewDialog({ reference: initialReference, candidate, initialView, onView, onClose, onSaved, workspace, onWorkspace, setBrowse, onOpenSet, onShowSet, jobRunning = false, onNotice, onKeep }: SetActions & {
  workspace: ComparisonState; onWorkspace: (state: ComparisonState) => void;
  reference: number; candidate: number | null; initialView: { threshold: number; page: number };
  onView: (view: { threshold: number; page: number }) => void; onClose: () => void; onSaved: () => void;
  // Another job holds the engine, so Reject waits.
  jobRunning?: boolean;
  // A note for the Library after the comparison closes (its reference was rejected).
  onNotice?: (text: string, actions: { label: string; run: () => void }[], photo?: number) => void;
  // Keep the reference and reject the rest: the same review as in Similar photos.
  onKeep?: (keep: number, name: string, threshold: number) => void;
}) {
  const [reference, setReference] = useState(workspace.reference);
  const [active, setActive] = useState<number | null>(candidate);
  const [threshold, setThreshold] = useState(workspace.threshold);
  const [page, setPage] = useState(workspace.page);
  const [filter, setFilter] = useState<ComparisonState["filter"]>(workspace.filter);
  const [matches, setMatches] = useState<MatchPage | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [review, setReview] = useState<MatchReview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [revision, setRevision] = useState(0);
  const [views, setViews] = useState<Record<number, PreviewView>>(workspace.views);
  const [linked, setLinked] = useState(workspace.linked);
  const [share, setShare] = useState(workspace.share);
  const layout = useRef<HTMLDivElement>(null);
  const selectLast = useRef(false);
  const focusReference = useRef(false);
  const [tab, setTab] = useState<"information" | "review">(workspace.tab);
  // Rejecting from the comparison (webui-spec 7.8): asked first, until "Don't ask again
  // while comparing", which lasts while this comparison is open; one reject at a time.
  const [dontAsk, setDontAsk] = useState(false);
  const [asking, setAsking] = useState<{ photo: MatchPhoto; isReference: boolean; last: boolean } | null>(null);
  const [rejecting, setRejecting] = useState<number | null>(null);
  const [rejectedHere, setRejectedHere] = useState(0);
  const [note, setNote] = useState<{ id: number; filename: string; returned: boolean } | null>(null);
  const [rejectError, setRejectError] = useState<string | null>(null);
  // The reference as last loaded, so it stays on screen once no look-alike is left.
  const [lastReference, setLastReference] = useState<MatchPhoto | null>(null);
  // After a reject, the look-alike at the rejected one's place is shown next.
  const pickIndex = useRef<number | null>(null);

  useEffect(() => {
    // Keep only the current pair's transforms in the bounded bookmark. Other
    // candidates retain their local views until this workspace closes/reloads.
    const current: Record<number, PreviewView> = { [reference]: views[reference] ?? DEFAULT_VIEW };
    if (active != null) current[active] = views[active] ?? DEFAULT_VIEW;
    onWorkspace({ origin:initialReference, reference, candidate:active, threshold, page, filter, tab,
      views:current, linked, share });
  }, [initialReference, reference, active, threshold, page, filter, tab, views, linked, share, onWorkspace]);

  useEffect(() => {
    let live = true;
    setMatches(null); setListError(null);
    api.matches(new URLSearchParams({ threshold: String(threshold), page: String(page), page_size: String(PAGE_SIZE), review_state: filter }), reference)
      .then(data => {
        if (!live) return;
        const last = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
        if (page > last) { setPage(last); return; }
        setMatches(data);
        const picked = pickIndex.current;
        pickIndex.current = null;
        setActive(old => old ?? (picked != null ? data.items[Math.min(picked, data.items.length - 1)]?.id
          : selectLast.current ? data.items.at(-1)?.id : data.items[0]?.id) ?? null);
        selectLast.current = false;
      }, e => { if (live) setListError(e instanceof Error ? e.message : "Candidates could not be loaded."); });
    return () => { live = false; };
  }, [reference, threshold, page, filter, reload, revision]);

  useEffect(() => {
    let live = true;
    setReview(null); setError(null);
    if (active != null) api.matchReview(reference, active).then(r => { if (live) { setReview(r); setLastReference(r.reference); } },
      e => { if (live) setError(e instanceof Error ? e.message : "The comparison could not be loaded."); });
    return () => { live = false; };
  }, [reference, active, reload]);

  useEffect(() => {
    if (focusReference.current && review?.reference.id === reference && review.candidate.id === active) {
      layout.current?.querySelector<HTMLElement>('[data-reference=true]')?.focus({ preventScroll: true });
      focusReference.current = false;
    }
  }, [review, reference, active]);

  const save = async (verdict: MatchVerdict | null) => {
    if (!review || busy) return;
    setBusy(true); setError(null);
    try { setReview(await api.saveMatchReview(review, verdict)); setRevision(n => n + 1); onSaved(); }
    catch (e) { setError(e instanceof Error ? e.message : "Your review could not be saved. Refresh and try again."); }
    finally { setBusy(false); }
  };
  const close = () => {
    // The gallery still shows its original reference. Pages from another photo's
    // match set cannot be applied to that original Inspector.
    onView({ threshold, page: reference === initialReference ? (filter === "all" ? page : 1) : initialView.page });
    onClose();
  };
  const changeView = (id: number, next: PreviewView) => setViews(old => {
    const other = id === reference ? active : reference;
    return { ...old, [id]: next, ...(linked && other != null ? { [other]: {
      ...(old[other] ?? DEFAULT_VIEW), zoom: next.zoom, x: next.x, y: next.y,
    } } : {}) };
  });
  const index = matches?.items.findIndex(p => p.id === active) ?? -1;
  const pages = Math.max(1, Math.ceil((matches?.total ?? 0) / PAGE_SIZE));
  const step = (delta: number) => {
    if (!matches || busy) return;
    const next = matches.items[index + delta];
    if (next) setActive(next.id);
    else if ((delta > 0 && page < pages) || (delta < 0 && page > 1)) {
      selectLast.current = delta < 0; setActive(null); setPage(n => n + delta);
    }
  };
  const resize = (value: number) => setShare(Math.min(82, Math.max(50, Math.round(value))));
  const referenceView = views[reference] ?? DEFAULT_VIEW;
  const candidateView = active == null ? DEFAULT_VIEW : views[active] ?? DEFAULT_VIEW;
  const displayedCandidateView = linked ? { ...candidateView, zoom: referenceView.zoom, x: referenceView.x, y: referenceView.y } : candidateView;
  const useAsReference = () => {
    if (busy || error || active == null || review?.reference.id !== reference || review.candidate.id !== active) return;
    setViews(old => ({ ...old, [active]: displayedCandidateView }));
    setReference(active);
    setActive(reference);
    setPage(1); setFilter("all"); selectLast.current = false;
    setReview(null); setMatches(null); setError(null); setListError(null);
    focusReference.current = true;
  };
  // Rejecting: the photo under the button goes, after the question unless the user said
  // not to ask; leaving none of the compared photos in the library always asks.
  const remaining = matches?.unfiltered_total ?? matches?.total ?? 0;
  const askReject = (photo: MatchPhoto, isReference: boolean) => {
    const last = isReference && remaining === 0;
    setRejectError(null);
    if (dontAsk && !last) void reject(photo, isReference);
    else setAsking({ photo, isReference, last });
  };
  const reject = async (photo: MatchPhoto, isReference: boolean) => {
    setRejecting(photo.id); setRejectError(null);
    try {
      const run = await runAndWait("reject", [photo.id]);
      if (moved(run, "reject") === 0) {
        setRejectError(`${photo.filename} was not rejected. The job's log says why.`);
        return;
      }
      onSaved();
      if (isReference) {
        onNotice?.(`Rejected ${photo.filename}.`, [{ label: "Return it to the library", run: () => { void runAndWait("return", [photo.id]); } }], photo.id);
        close();
        return;
      }
      setRejectedHere(n => n + 1);
      setNote({ id: photo.id, filename: photo.filename, returned: false });
      pickIndex.current = Math.max(0, index);
      setActive(null); setReview(null); setRevision(n => n + 1);
    } catch (e) {
      setRejectError(e instanceof Error ? e.message : `${photo.filename} could not be rejected.`);
    } finally { setRejecting(null); }
  };
  const returnNoted = async () => {
    if (!note) return;
    setRejecting(note.id); setRejectError(null);
    try {
      const run = await runAndWait("return", [note.id]);
      if (moved(run, "return") === 0) setRejectError(`${note.filename} was not returned. The job's log says why.`);
      else { setNote({ ...note, returned: true }); setRejectedHere(n => Math.max(0, n - 1)); setRevision(n => n + 1); onSaved(); }
    } catch (e) {
      setRejectError(e instanceof Error ? e.message : `${note.filename} could not be returned.`);
    } finally { setRejecting(null); }
  };
  const rejectButton = (photo: MatchPhoto, isReference: boolean) => (
    <button className="photo-action" disabled={busy || rejecting != null || jobRunning}
            title={jobRunning ? "A job is running. Wait for it to finish or cancel it." : `Move ${photo.filename} out of the library into Rejects. Nothing is deleted.`}
            onClick={() => askReject(photo, isReference)}>
      {rejecting === photo.id ? "Rejecting…" : "Reject…"}
    </button>
  );
  const noteLine = note && (note.returned
    ? <>Returned {note.filename} to the library.</>
    : <>Rejected {note.filename} · {remaining > 0 ? "next look-alike shown" : "no more look-alikes"}{" "}
        <button className="link" disabled={rejecting != null} onClick={() => void returnNoted()}>Return it to the library</button></>);
  // Candidate position across pages, for the frame's ‹ n of N ›.
  const position = matches && index >= 0 ? (page - 1) * PAGE_SIZE + index + 1 : null;
  const progress = matches?.availability === "available"
    ? `${count(matches.reviewed_total ?? 0)} of ${count(matches.unfiltered_total ?? matches.total)} pairs reviewed at this threshold`
    : "Loading review progress…";
  return <Workspace label="Review photo match" className="match-review-dialog" onBack={close} busy={busy}
    title="Review similar photos"
    subject={review?.reference.id === reference ? `Reference: ${review.reference.filename}` : "Compare destination photos and record what you find."}
    step={{
      position: position == null ? "Candidates" : `Candidate ${count(position)} of ${count(matches!.total)}`,
      previousLabel: "Previous candidate", nextLabel: "Next candidate",
      onPrevious: () => step(-1), onNext: () => step(1),
      previousDisabled: !matches || (index <= 0 && page === 1),
      nextDisabled: !matches?.items.length || (index === matches.items.length - 1 && page === pages),
    }}
    status={noteLine ?? progress}>
    <ReviewActions workspace={{ origin: initialReference, reference, candidate: active, threshold, page, filter, tab,
      views: { [reference]: referenceView, ...(active == null ? {} : { [active]: displayedCandidateView }) }, linked, share }}
      busy={busy || !review} setBrowse={setBrowse} onOpenSet={onOpenSet} onShowSet={onShowSet} />
    <div className="review-toolbar">
      <label>Minimum similarity<select aria-label="Minimum similarity" disabled={busy} value={threshold} onChange={e => {
        setThreshold(Number(e.target.value)); setPage(1); setActive(null);
      }}>{MATCH_THRESHOLDS.map(t => <option key={t} value={t}>{t}% or higher</option>)}</select></label>
      <label>Review progress<select aria-label="Review progress" disabled={busy} value={filter} onChange={e => {
        setFilter(e.target.value as ComparisonState["filter"]); setPage(1); setActive(null);
      }}><option value="all">All candidates</option><option value="unreviewed">Unreviewed</option><option value="reviewed">Reviewed</option></select></label>
      <button disabled={busy} onClick={() => setReload(n => n + 1)}>Refresh comparison</button>
      {onKeep && lastReference?.id === reference && remaining > 0 && <button className="photo-action review-keep"
        disabled={busy || rejecting != null || jobRunning}
        title={jobRunning ? "A job is running. Wait for it to finish or cancel it." : "Review the look-alikes before any is rejected. To keep the other photo, use it as the reference first."}
        onClick={() => { const name = lastReference.filename; close(); onKeep(reference, name, threshold); }}>
        Keep {lastReference.filename}, reject the other {count(remaining)}…
      </button>}
    </div>
    <p className="section-note">Scores measure visual similarity, not confidence. Even 100% can describe different pictures.
      {threshold < 90 && " Below 90%, results are more likely to be unrelated. Review photos before using them as metadata clues."}</p>
    {error && <p className="error" role="alert">{error} <button disabled={busy} onClick={() => setReload(n => n + 1)}>Retry comparison</button></p>}
    {rejectError && <p className="error" role="alert">{rejectError}</p>}
    {matches?.availability === "available" && remaining === 0 && lastReference?.id === reference && <div className="review-alone">
      <p role="status">No more look-alikes at this threshold.</p>
      <div className="review-pair"><ReviewPreview label="Reference" isReference photo={lastReference} view={referenceView}
        onChange={next => changeView(reference, next)} refreshKey={reload} action={rejectButton(lastReference, true)} /></div>
    </div>}
    {asking && <RejectConfirm filename={asking.photo.filename} last={asking.last} rejectedHere={rejectedHere} offerDontAsk
      onCancel={() => setAsking(null)}
      onConfirm={(again) => { const { photo, isReference } = asking; setAsking(null); if (again) setDontAsk(true); void reject(photo, isReference); }} />}
    {!review && active != null && !error && <p role="status">Loading comparison…</p>}
    {review && review.reference.id === reference && review.candidate.id === active && <>
      <div className="review-layout" ref={layout} style={{ "--review-share": `${share}%` } as CSSProperties}>
        <div className="review-comparison">
          <div className="review-previews">
          <div className="review-pair">
            <ReviewPreview label="Reference" isReference photo={review.reference} view={referenceView}
              onChange={next => changeView(reference, next)} refreshKey={reload}
              action={rejectButton(review.reference, true)} />
            <ReviewPreview label="Candidate" photo={review.candidate} view={displayedCandidateView}
              onUseAsReference={useAsReference} referenceDisabled={busy || !!error}
              onChange={next => changeView(active, next)} refreshKey={reload}
              action={rejectButton(review.candidate, false)} />
          </div>
          <div className="review-pair-options">
            <label><input type="checkbox" checked={linked} onChange={e => {
              setLinked(e.target.checked);
              if (!e.target.checked) setViews(old => ({ ...old, [active]: displayedCandidateView }));
              if (e.target.checked) setViews(old => ({ ...old, [active]: { ...(old[active] ?? DEFAULT_VIEW),
                zoom: (old[reference] ?? DEFAULT_VIEW).zoom, x: (old[reference] ?? DEFAULT_VIEW).x, y: (old[reference] ?? DEFAULT_VIEW).y } }));
            }} />Link zoom and position</label>
            <span className="section-note">Rotation is for viewing only. Zoom uses previews up to 1024 pixels.</span>
          </div>
          </div>
          <fieldset disabled={busy || !!error} className="review-verdicts"><legend>This pair</legend>
            {VERDICTS.map(([value, label]) => <button key={value} disabled={review.exact} aria-pressed={review.feedback?.verdict === value}
              onClick={() => save(value)}>{label}</button>)}
            <button disabled={!review.feedback} onClick={() => save(null)}>Clear judgment</button>
          </fieldset>
          <p className="review-save-status" role="status">{busy ? "Saving judgment…" : review.feedback
            ? `Saved: ${verdictName(review.feedback.verdict)} · ${instant(review.feedback.updated_at)}` : "No judgment recorded. You can move on without deciding."}</p>
        </div>
        <div className="review-divider" role="separator" tabIndex={0} aria-label="Resize comparison and information" aria-orientation="vertical"
          aria-valuemin={50} aria-valuemax={82} aria-valuenow={share}
          onKeyDown={e => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
            e.preventDefault(); resize(e.key === "Home" ? 50 : e.key === "End" ? 82 : share + (e.key === "ArrowRight" ? 2 : -2));
          }} onPointerDown={e => { e.currentTarget.setPointerCapture(e.pointerId); e.preventDefault(); }}
          onPointerMove={e => { if (e.currentTarget.hasPointerCapture(e.pointerId) && layout.current) {
            const box = layout.current.getBoundingClientRect(); resize(100 * (e.clientX - box.left) / box.width);
          } }} onPointerUp={e => { if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId); }} />
        <aside className="review-information">
          <div className="review-info-tabs" role="tablist" aria-label="Comparison details">
            {(["information", "review"] as const).map(value => <button key={value} id={`review-tab-${value}`} role="tab"
              aria-selected={tab === value} tabIndex={tab === value ? 0 : -1} aria-controls={`review-panel-${value}`}
              onClick={() => setTab(value)} onKeyDown={e => {
                if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
                e.preventDefault(); const next = e.key === "Home" ? "information" : e.key === "End" ? "review" : value === "information" ? "review" : "information";
                setTab(next); document.getElementById(`review-tab-${next}`)?.focus();
              }}>{value === "information" ? "Information" : "Saved review"}</button>)}
          </div>
          <div role="tabpanel" id="review-panel-information" aria-labelledby="review-tab-information" hidden={tab !== "information"}>
            <ReviewMetadata reference={reference} candidate={active} refreshKey={reload} />
          </div>
          <div role="tabpanel" id="review-panel-review" aria-labelledby="review-tab-review" hidden={tab !== "review"}>
            <h3>Saved review</h3><p>{verdictName(review.feedback?.verdict)}</p>
            {review.feedback && <p className="section-note">Last saved {instant(review.feedback.updated_at)}. This judgment belongs to these two file contents.</p>}
            <p className="section-note">Judgments are saved in the catalog. They do not change photos, metadata, or matching results.</p>
          </div>
          <p className="review-score">{review.score == null ? "Visual hash unavailable" : `${review.score}% visual similarity`}</p>
          <p className="section-note">{review.exact ? "Identical bytes (same SHA-1)." : "Different bytes (different SHA-1)."}</p>
          {review.score != null && review.score < 90 && <p className="section-note">Below 90%, results are more likely to be unrelated. Review photos side by side before using them as clues for dates or other details.</p>}
        </aside>
      </div>
    </>}
    <section className="review-candidates" aria-label="Candidate photos">
      <div className="review-candidate-heading"><h3>Candidates</h3></div>
      {listError && <p className="error" role="alert">{listError} <button disabled={busy} onClick={() => setReload(n => n + 1)}>Retry candidates</button></p>}
      {!matches && !listError && <p role="status">Loading candidates…</p>}
      {matches?.availability && matches.availability !== "available" && <p>Matching is unavailable. A recorded destination copy and usable visual hash are required.</p>}
      <SimilarityRecovery visible={matches?.availability === "available" && matches.state.pending > 0} onRecovered={() => setReload(n => n + 1)} />
      {matches?.availability === "available" && <>
        {matches.state.pending > 0 && <p className="section-note">Results are incomplete: {count(matches.state.pending)} destination photos awaiting comparison.</p>}
        {matches.total === 0 && <p>No {filter === "all" ? "" : `${filter} `}candidates at this threshold.</p>}
        <ul className="review-filmstrip">{matches.items.map(photo => <li key={photo.id}>
          <button disabled={busy} aria-pressed={active === photo.id} aria-label={`Compare ${photo.filename}`} onClick={() => setActive(photo.id)}>
            <Thumb id={photo.id} alt="" refreshKey={reload} /><span title={photo.filename}>{photo.filename}</span>
            <span>{photo.score}% · {verdictName(photo.verdict)}</span>
          </button>
        </li>)}</ul>
        {pages > 1 && <nav className="match-pages" aria-label="Candidate pages">
          <button disabled={busy || page <= 1} onClick={() => { setActive(null); setPage(n => n - 1); }}>Previous page</button>
          <span>Page {count(page)} of {count(pages)}</span>
          <button disabled={busy || page >= pages} onClick={() => { setActive(null); setPage(n => n + 1); }}>Next page</button>
        </nav>}
      </>}
    </section>
  </Workspace>;
}
