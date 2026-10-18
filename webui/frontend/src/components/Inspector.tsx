import { RotationControls, useRotationSave } from "./RotationControls";
import { useRotationExit } from "./RotationEditor";
import { blockingDateIssue, captureDateMessage } from "../photoDates";
import { FileLocations } from "./ui/FileLocations";
import { ImportChoiceDialog } from "./ImportChoices";
import { FileIssues } from "./FileIssues";
import { ReviewNote } from "./ReviewNote";
import { TabList, tabPanel } from "./ui/Tabs";
import type { SetActions } from "./ReviewActions";
import type { ComparisonState } from "../comparisonState";
import { Modal } from "./ui/Modal";
import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { api, ApiError, type PhotoDetail, type MetadataSourceView, type Operation } from "../api";
import { bytes, epoch, isFallbackDate } from "../format";
import { follow, logUrl } from "../nav";
import { PrimarySourceEditor } from "./PrimarySourceEditor";
import { DateEditor } from "./DateEditor";
import { MetadataSources } from "./MetadataSources";
import { LineageDialog } from "./LineageDialog";
import { jobLabel, operationLabel } from "../jobs";
import { Thumb } from "./Thumb";
import { PhotoMatches, type MatchView } from "./PhotoMatches";
import { MatchReviewDialog } from "./MatchReviewDialog";
import { SearchField } from "./ui/SearchField";

const STATUS: Record<string, string> = {
  Pending: "Not yet organized", Processing: "In progress", Completed: "Moved to the destination",
  Copied: "Copied to the destination", Failed: "Failed", Duplicate: "Duplicate (source still on disk)",
  Removed_Duplicate: "Duplicate (source removed)", Found_At_Destination: "Found at the destination",
  Rejected: "In Rejects", Rejected_Copied: "In Rejects (source still in place; a Move removes it)",
  Rejected_Emptied: "Rejected; since emptied from Rejects",
};
// Photos in the library, which can be rejected, and photos in Rejects, which can go back.
const IN_LIBRARY = ["Completed", "Copied", "Found_At_Destination"];
const IN_REJECTS = ["Rejected", "Rejected_Copied"];


// The split-screen Inspector (webui-spec 4.2): the grid thumbnail at once, the
// 1024px preview as soon as the engine has made it, and what the catalog records.
// When the panel is dragged wide, the details move to the right of the photo
// and the inner divider adjusts their share of space. Enlarging uses this same
// two-pane Inspector in a modal; Esc or the close button returns to the gallery.
export function Inspector({ id, enlarged, setEnlarged, leaveGuard, statusHint, sourceView = false, width, onClose, onStep, onOpenPhoto, jobRunning, refreshKey, matchView, onMatchView, tab, onTab, comparison, onComparison, setBrowse, onOpenSet, onShowSet, onReject, onReturn, onRejectMatch, onKeep, onNotice, onReviewPhoto }: SetActions & {
  // Reject this photo, or return it from Rejects; each asks first.
  onReject?: (filename: string) => void;
  onReturn?: () => void;
  onReviewPhoto?: () => void;
  // From Similar photos: reject one look-alike, or keep this photo and reject the rest.
  onRejectMatch?: (id: number, filename: string) => void;
  onKeep?: (keep: number, name: string, threshold: number) => void;
  onNotice?: (text: string, actions: { label: string; run: () => void }[], photo?: number) => void;
  comparison: ComparisonState | null;
  onComparison: (state: ComparisonState | null) => void;
  leaveGuard: { current: (action: () => void) => void };
  id: number;
  enlarged: boolean;
  setEnlarged: (enlarged: boolean) => void;
  // Gallery status reserves the correct tabs while details load; never authorizes actions.
  statusHint?: string;
  sourceView?: boolean;
  width: number | null;
  onClose: () => void;
  onStep: (delta: number) => void;
  // Opens another photo in the panel: a duplicate, from the lineage tree.
  onOpenPhoto: (id: number) => void;
  jobRunning: boolean;
  refreshKey: number;
  tab: "information" | "metadata" | "similar";
  onTab: (tab: "information" | "metadata" | "similar") => void;
  matchView: MatchView;
  onMatchView: (view: MatchView) => void;
}) {
  const [turns, setTurns] = useState(0);
  const saver = useRotationSave((_id, survivor) => {
    setTurns(0);
    if (survivor != null) {
      onNotice?.("Rotation saved. The existing photo was kept; both histories are preserved.", [], survivor);
      // This confirmed save has settled the only pending turn. The navigation
      // guard still sees the preceding render's busy state until React commits.
      leaveGuard.current = action => action();
      onOpenPhoto(survivor);
    }
  });
  const rotationExit = useRotationExit([{ photo_id: id, turns }], () => setTurns(0), jobRunning, saver.busy);
  useLayoutEffect(() => {
    leaveGuard.current = rotationExit.requestLeave;
    return () => { leaveGuard.current = action => action(); };
  });
  const close = () => rotationExit.requestLeave(onClose);
  const step = (delta: number) => rotationExit.requestLeave(() => onStep(delta));
  const imageFrame = useRef<HTMLDivElement>(null);
  const [imageSize, setImageSize] = useState({ width: 1, height: 1 });
  const [importChoices, setImportChoices] = useState(false);
  const [dateEdit, setDateEdit] = useState<{ photoId: number; donor?: MetadataSourceView } | null>(null);
  const [primaryEdit, setPrimaryEdit] = useState<{ photoId: number; source: MetadataSourceView; captureId: number } | null>(null);
  const editDate = (donor?: MetadataSourceView) => { onTab("metadata"); setDateEdit({ photoId:id, donor }); };
  const openMetadata = () => { onTab("metadata"); requestAnimationFrame(() => document.getElementById(`${tabId}-metadata`)?.focus()); };
  const [narrow, setNarrow] = useState(() => window.matchMedia("(max-width: 800px)").matches);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 800px)");
    const update = () => setNarrow(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useLayoutEffect(() => {
    const el = imageFrame.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setImageSize({ width: el.clientWidth, height: el.clientHeight }));
    observer.observe(el); return () => observer.disconnect();
  }, [enlarged, narrow]);
  const tabId = useId();
  const panel = useRef<HTMLElement>(null);
  const header = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    if (!header.current) return;
    const observer = new ResizeObserver(([entry]) => panel.current?.style.setProperty(
      "--inspector-head-h", `${Math.ceil(entry.target.getBoundingClientRect().height)}px`));
    observer.observe(header.current);
    return () => observer.disconnect();
  }, [narrow, enlarged]);
  const [previewShare, setPreviewShare] = useState(() => {
    try {
      const saved = Number(localStorage.getItem("ns.inspectorPreviewShare"));
      if (Number.isFinite(saved) && saved >= 20 && saved <= 75) return saved;
    } catch { /* Browser storage is optional. */ }
    return 50;
  });
  const [splitSize, setSplitSize] = useState({ wide: false, width: 640, height: 480 });
  useLayoutEffect(() => {
    const el = panel.current;
    if (!el) return;
    const update = () => setSplitSize({ wide: el.clientWidth >= 1000, width: el.clientWidth - 24,
      height: Math.max(160, el.clientHeight - (header.current?.clientHeight ?? 0) - 24) });
    const observer = new ResizeObserver(update);
    observer.observe(el);
    if (header.current) observer.observe(header.current);
    update();
    return () => observer.disconnect();
  }, [narrow, enlarged]);
  const wasEnlarged = useRef(false);
  useLayoutEffect(() => {
    const restore = wasEnlarged.current && !enlarged;
    wasEnlarged.current = enlarged;
    if (!restore) return;
    const frame = requestAnimationFrame(() => panel.current?.querySelector<HTMLElement>('.inspector-image')?.focus({ preventScroll: true }));
    return () => cancelAnimationFrame(frame);
  }, [enlarged]);
  const splitDrag = useRef<{ position: number; share: number; extent: number } | null>(null);
  const resizePreview = (share: number) => {
    const value = Math.min(75, Math.max(20, Math.round(share)));
    setPreviewShare(value);
    try { localStorage.setItem("ns.inspectorPreviewShare", String(value)); } catch { /* Optional preference. */ }
  };
  const [detail, setDetail] = useState<PhotoDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [previewReady, setPreviewReady] = useState(false);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [lineage, setLineage] = useState(false);
  const inLibrary = !!detail && detail.id === id && IN_LIBRARY.includes(detail.status);
  const canCompare = inLibrary || (!!detail && detail.id === id && IN_REJECTS.includes(detail.status));
  const layoutStatus = detail?.id === id ? detail.status : statusHint;
  const layoutInLibrary = layoutStatus != null && IN_LIBRARY.includes(layoutStatus);
  const layoutCanCompare = layoutStatus == null || layoutInLibrary || IN_REJECTS.includes(layoutStatus);
  const activeTab = tab === "similar" && !layoutCanCompare ? "information" : tab;
  useEffect(() => {
    if (detail?.id !== id || canCompare) return;
    if (tab === "similar") onTab("information");
    if (comparison != null) onComparison(null);
  }, [detail, id, canCompare, tab, comparison, onTab, onComparison]);
  const candidate = comparison?.candidate ?? null;
  const comparisonOpener = useRef<HTMLElement | null>(null);
  const closeComparison = () => {
    onComparison(null);
    requestAnimationFrame(() => {
      const target = comparisonOpener.current;
      (target?.isConnected ? target : panel.current?.querySelector<HTMLElement>('.inspector-match') ?? panel.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]'))?.focus({ preventScroll:true });
    });
  };
  const openComparison = (candidate: number, scope: "library" | "rejects" = "library", matchPage = matchView?.page ?? 1) => {
    comparisonOpener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    onComparison({ origin:id, reference:id, candidate, scope,
    threshold:matchView?.threshold ?? 90, page:matchPage,
    views:{}, linked:false, share:72 });
  };
  // Rejects and returns from the comparison, so Similar photos' diagnostics refresh.
  const [comparisonChanges, setComparisonChanges] = useState(0);
  useEffect(() => { setLineage(false); }, [id]);

  useEffect(() => {
    setDetail(null);
    setPreviewReady(false);
    setPreviewFailed(false);
  }, [id]);

  // Refresh metadata without replacing the preview or closing the panel.
  useEffect(() => {
    let live = true;
    setError(null);
    api.inspect(id).then(
      (d) => live && setDetail(d),
      (e) => live && setError(e instanceof ApiError ? e.message : "The photo could not be loaded."),
    );
    return () => {
      live = false;
    };
  }, [id, refreshKey]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (document.querySelector("dialog[open]") || (e.target as HTMLElement)?.closest("input, textarea, select, [role=menu]")) return;
      // Esc closes the enlarged view first, then the Inspector.
      if (e.key === "Escape") (enlarged ? setEnlarged(false) : close());
      if (e.key === "ArrowRight") step(1);
      if (e.key === "ArrowLeft") step(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, onStep, enlarged, turns, saver.busy]);

  const photo = (
    <div ref={imageFrame} className="inspector-turn-frame"><div className="inspector-turn" style={{ width: turns % 2 ? imageSize.height : imageSize.width,
      height: turns % 2 ? imageSize.width : imageSize.height, transform: `translate(-50%, -50%) rotate(${turns * 90}deg)` }}>
      {!previewReady && <Thumb refreshKey={refreshKey} id={id} alt={detail?.filename ?? ""} />}
      {!previewFailed && (
        <img
          key={id}
          src={api.thumbnailUrl(id, "preview", refreshKey)}
          alt={detail?.filename ?? ""}
          style={{ display: previewReady ? undefined : "none" }}
          onLoad={() => setPreviewReady(true)}
          onError={() => setPreviewFailed(true)}
        />
      )}
    </div></div>
  );

  const body = (
    <section ref={panel} className="inspector" data-tab={activeTab} aria-label="Photo details" style={!enlarged && width ? { flexBasis: `${width}px` } : undefined}
      onKeyDown={(e) => {
        if (!enlarged || e.defaultPrevented || !(e.target instanceof HTMLElement)) return;
        if (e.target.closest("dialog") !== panel.current?.closest("dialog") ||
            e.target.closest("input, textarea, select, [role=tablist], [role=separator], [role=menu]")) return;
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          e.preventDefault(); e.stopPropagation(); step(e.key === "ArrowLeft" ? -1 : 1);
        }
      }}>
      <header ref={header} className="inspector-head">
        <button onClick={() => step(-1)} aria-label="Previous photo">‹</button>
        <h2 title={detail?.filename}>{detail?.filename ?? "…"}</h2>
        <button onClick={() => step(1)} aria-label="Next photo">›</button>
        <button onClick={enlarged ? () => setEnlarged(false) : close} aria-label={enlarged ? "Close the enlarged photo" : "Close"} data-initial-focus={enlarged || undefined}>✕</button>
      </header>
      <div className="inspector-main" data-wide={splitSize.wide}
           style={{ "--preview-share": `${previewShare}%`,
             "--preview-size": `${Math.round(splitSize.height * (splitSize.wide ? 1 : previewShare / 100))}px` } as CSSProperties}>
        <div className="inspector-preview" data-reference={activeTab === "similar"}>
          {(activeTab === "similar" || (!sourceView && inLibrary)) && <div className="inspector-preview-tools">
            {activeTab === "similar" && <h3>Reference photo</h3>}
            {!sourceView && inLibrary && <RotationControls id={id} label="Photo" turns={turns} onChange={setTurns} saver={saver} jobRunning={jobRunning} refreshKey={refreshKey}/>}
          </div>}
          {enlarged ? <div className="inspector-image">{photo}</div> :
            <button className="inspector-image" disabled={saver.busy} onClick={() => setEnlarged(true)} aria-label="Enlarge the photo"
                    title="Click to enlarge">{photo}</button>}
        </div>
        <div className="preview-divider" role="separator" tabIndex={0}
             aria-label="Resize photo preview" aria-orientation={splitSize.wide ? "vertical" : "horizontal"}
             aria-valuemin={20} aria-valuemax={75} aria-valuenow={previewShare}
             aria-valuetext={`${previewShare}% for the photo preview`}
             title="Drag to resize the photo preview, or focus here and use the arrow keys"
             onPointerDown={(e) => {
               if (e.button !== 0) return;
               e.preventDefault(); e.currentTarget.focus(); e.currentTarget.setPointerCapture(e.pointerId);
               splitDrag.current = { position: splitSize.wide ? e.clientX : e.clientY, share: previewShare,
                 extent: splitSize.wide ? splitSize.width : splitSize.height };
             }}
             onPointerMove={(e) => {
               const drag = splitDrag.current;
               if (drag) resizePreview(drag.share + 100 * ((splitSize.wide ? e.clientX : e.clientY) - drag.position) / drag.extent);
             }}
             onPointerUp={(e) => { splitDrag.current = null; e.currentTarget.releasePointerCapture(e.pointerId); }}
             onLostPointerCapture={() => { splitDrag.current = null; }}
             onPointerCancel={() => { splitDrag.current = null; }}
             onKeyDown={(e) => {
               const before = splitSize.wide ? "ArrowLeft" : "ArrowUp";
               const after = splitSize.wide ? "ArrowRight" : "ArrowDown";
               if (![before, after, "Home", "End"].includes(e.key)) return;
               e.preventDefault(); e.stopPropagation();
               resizePreview(e.key === "Home" ? 20 : e.key === "End" ? 75 : previewShare + (e.key === before ? -5 : 5));
             }}><span aria-hidden="true">⋮⋮</span></div>
        <div className="inspector-side" aria-busy={detail == null && error == null}>
          {sourceView && (layoutInLibrary || (layoutStatus != null && IN_REJECTS.includes(layoutStatus))) && <p className="notice" role="note">
            The original remains in the source. This preview, metadata and photo actions refer to the {layoutInLibrary ? "Library" : "Rejects"} copy; its metadata may differ from the original.
          </p>}
          {error && <p className="error">{error}</p>}
          <div style={{ flexShrink: 0, visibility: layoutStatus == null ? "hidden" : undefined }} aria-hidden={layoutStatus == null ? true : undefined}>
            <TabList className="inspector-tabs" label="Photo inspector" idBase={tabId} value={activeTab} onChange={onTab}
              tabs={[{ value: "information", label: layoutInLibrary ? "Photo information" : "File information" }, { value: "metadata", label: "Metadata" }, ...(layoutCanCompare ? [{ value: "similar" as const, label: layoutInLibrary ? "Similar photos" : "Similar photos in Library" }] : [])]} />
          </div>
          <div className="inspector-tab-panel" role="tabpanel" {...tabPanel(tabId, "information", activeTab)}>
            {detail && activeTab === "information" && <Details onImportChoices={() => setImportChoices(true)} onMetadata={openMetadata} onEdit={editDate} jobRunning={jobRunning} refreshKey={refreshKey} detail={detail} onLineage={() => setLineage(true)}
              review={inLibrary ? <ReviewNote key={`review:${id}`} id={id} refreshKey={refreshKey} disabled={jobRunning} compact onOpenReview={onReviewPhoto ? () => rotationExit.requestLeave(onReviewPhoto) : undefined}
                concerns={detail.date_warning ? [{label:"Suspicious date",message:`${detail.date_warning} Recorded value: ${detail.date_taken}. Source: ${isFallbackDate(detail.date_source) ? "file modification fallback" : detail.date_source === "exif" ? "photo EXIF" : detail.date_source ?? "unknown"}. Use Edit date or the Metadata tab to correct the date.`}]
                  : captureDateMessage(detail) ? [{label:"No usable capture date",message:captureDateMessage(detail)!}] : []}
                actions={IN_LIBRARY.includes(detail.status) && onReject
                  ? <button onClick={() => rotationExit.requestLeave(() => onReject(detail.filename))} disabled={jobRunning} title={jobRunning ? "Wait for the running job to finish." : "Move this photo to Rejects. Nothing is deleted."}>Reject…</button>
                  : null} /> : IN_REJECTS.includes(detail.status) && onReturn ? <div className="photo-actions"><button onClick={onReturn} disabled={jobRunning} title={jobRunning ? "Wait for the running job to finish." : undefined}>Return to library…</button></div> : null} />}
          </div>
          <div className="inspector-tab-panel" role="tabpanel" {...tabPanel(tabId, "metadata", activeTab)}>
            {detail && activeTab === "metadata" && <div className="inspector-body">
              <MetadataSources onPrimary={(source, captureId) => setPrimaryEdit({photoId:detail.id, source, captureId})} onEdit={editDate} key={`metadata:${detail.id}`} photoId={detail.id} refreshKey={refreshKey} editable={inLibrary} jobRunning={jobRunning} />
            </div>}
          </div>
          <div className="inspector-tab-panel" role="tabpanel" {...tabPanel(tabId, "similar", activeTab)}>
            {detail && activeTab === "similar" && <div className="inspector-body"><PhotoMatches key={id} id={id} name={detail.filename}
              jobRunning={jobRunning} onReject={onRejectMatch ? (photo) => onRejectMatch(photo.id, photo.filename) : undefined}
              onKeep={inLibrary && onKeep ? (threshold) => onKeep(id, detail.filename, threshold) : undefined}
              delivered={canCompare} rejected={!inLibrary}
              view={matchView} onView={onMatchView} refreshKey={refreshKey}
              onReview={(...args) => rotationExit.requestLeave(() => openComparison(...args))} changes={comparisonChanges} /></div>}
          </div>
        </div>
      </div>

    </section>
  );
  return <>
    {lineage && detail && <LineageDialog photoId={id} filename={detail.filename} jobRunning={jobRunning}
      onOpenPhoto={(other) => rotationExit.requestLeave(() => { setLineage(false); onOpenPhoto(other); })} onClose={() => setLineage(false)} />}
    {rotationExit.editor}
    {importChoices && <ImportChoiceDialog photoId={id} onClose={() => setImportChoices(false)} />}
    {primaryEdit && <PrimarySourceEditor {...primaryEdit} onClose={() => setPrimaryEdit(null)} onSaved={() => window.dispatchEvent(new Event("ns-review-changed"))} />}
    {dateEdit && <DateEditor photoId={dateEdit.photoId} donor={dateEdit.donor} onClose={() => setDateEdit(null)} onSaved={() => window.dispatchEvent(new Event("ns-review-changed"))} />}
    {enlarged && !narrow && <div className="inspector-placeholder" aria-hidden="true" style={width ? { flexBasis: `${width}px` } : undefined} />}
    {enlarged ? <Modal className="lightbox" label={`Enlarged: ${detail?.filename ?? ""}`} onClose={() => setEnlarged(false)}>{body}</Modal>
      : narrow && comparison == null ? <Modal deferWhileCovered className="mobile-inspector" label="Photo details" onClose={close}>{body}</Modal> : body}
    {canCompare && comparison != null && <MatchReviewDialog reference={id} candidate={candidate} jobRunning={jobRunning} onNotice={onNotice} onKeep={onKeep}
      workspace={comparison} onWorkspace={onComparison} setBrowse={setBrowse} onOpenSet={onOpenSet} onShowSet={onShowSet}
      initialView={matchView ?? { threshold: 90, page: 1 }} onView={onMatchView}
      onClose={closeComparison} onChanged={() => setComparisonChanges((n) => n + 1)} />}
  </>;
}

function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <tr>
      <th scope="row">{label}</th>
      <td>{children}</td>
    </tr>
  );
}

// One bordered table per section; every table has the same width and label column.
function Section({ title, note, children }: { title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section className="info-section">
      <h3>{title}</h3>
      {note && <p className="section-note">{note}</p>}
      <table className="info">
        <tbody>{children}</tbody>
      </table>
    </section>
  );
}

function Details({ onImportChoices, detail: d, onLineage, refreshKey, review, jobRunning, onEdit, onMetadata }: { onImportChoices: () => void; onMetadata: () => void; onEdit: (donor?: MetadataSourceView) => void; jobRunning: boolean; detail: PhotoDetail; onLineage: () => void; refreshKey: number; review?: ReactNode }) {
  const fallback = isFallbackDate(d.date_source);
  return (
    <div className="inspector-body">
      <FileIssues key={`issues:${d.id}`} photoId={d.id} initialIssues={d.issues ?? []} />
      {d.metadata_attention && <section className="notice" aria-label="Metadata needs attention">
        <strong>Needs attention before organizing</strong>
        <p>This photo cannot be organized yet. It and its associated sidecars stay in the source.</p>
        {d.metadata_attention.issues.map((issue, i) => <div key={i}>
          <p>{issue.reason}</p>
          {issue.files.map(file => <p key={file}>File in your source folder:<br /><code>{file}</code></p>)}
          {issue.detail && <p className="section-note">Recorded detail: {issue.detail}</p>}
        </div>)}
        <p>{d.metadata_attention.action}</p>
        <div className="settings-actions">
        {d.status === "Pending" && d.metadata_attention.issues.some(i=>["ambiguous_ownership","owner_conflict","saved_owner_changed","metadata_choice_needed"].includes(i.code)) && <button className="photo-action" disabled={jobRunning} title={jobRunning ? "Wait for the running job to finish." : undefined} onClick={onImportChoices}>Resolve XMP choices…</button>}
        <a href={logUrl({photo:d.id})} onClick={follow}>View photo logs</a>
        </div>
      </section>}
      {review}
      {!review && IN_LIBRARY.includes(d.status) && d.date_warning && <p className="section-note"><strong>Suspicious date:</strong> {d.date_warning} Recorded value: {d.date_taken}. Source: {fallback ? "file modification fallback" : d.date_source === "exif" ? "photo EXIF" : d.date_source ?? "unknown"}. Check the recorded metadata or compare similar photos for clues. Use Edit date or the Metadata tab to correct it. <a href="/?view=suspicious">View suspicious dates</a></p>}
      {IN_LIBRARY.includes(d.status) && d.visual_issue && <p className="section-note"><strong>Visual matching unavailable:</strong> {d.visual_issue} The catalogued file is retained. Missing EXIF alone is not evidence of damage.</p>}
      {d.status === "Failed" && !d.issues?.length && <p className="notice"><strong>File needs attention.</strong> {d.failure ?? "No failure reason was recorded."} This file is not in Library. Fix the source file or its access outside the app, then run Index again. <a href={logUrl({photo:d.id,status:"Failed"})} onClick={follow}>View failure details</a></p>}
      <Section title="File">
        <Row label="Status">{STATUS[d.status] ?? d.status}</Row>
        <Row label="Format">{d.filename.includes(".") ? d.filename.split(".").pop()!.toUpperCase() : "Not recorded"}</Row>
        <Row label="Date taken">
          {fallback || !d.date_taken ? (blockingDateIssue(d) ? "See the date issue above." : "No usable capture date") : d.date_taken.replace("T", " ")}
          <div className="muted">{fallback ? "File modification year is used for Undated filing." : d.date_source === "exif" ? "Filing date from EXIF" : d.date_source === "xmp" ? "Filing date from XMP" : "Filing date source not recorded"}</div>
          <div className="history-links"><button className="link" onClick={onMetadata}>View metadata</button>
            {IN_LIBRARY.includes(d.status) && <button className="link" disabled={jobRunning} title={jobRunning ? "Wait for the running job to finish." : undefined} onClick={() => onEdit()}>Edit metadata date…</button>}</div>
        </Row>
        <tr><td colSpan={2}><FileLocations
          source={[{label:"Source path",path:d.source_path ?? "—"}]}
          destinationLabel={d.dest_path_is_projection ? "Proposed destination" : "Destination"}
          destination={[{label:d.dest_path_is_projection ? "Proposed destination path" : "Destination path",path:d.dest_path ?? "—",
            note:<>{d.dest_path_is_projection && <div>Not written yet.</div>}{d.has_collision_rename && <div>Renamed: another file already had this name.</div>}</>}]} />
        </td></tr>
        <Row label="Size">{bytes(d.file_size)}{d.width && d.height ? ` · ${d.width} × ${d.height}` : ""}</Row>
        <Row label={<span className="row-tip" title="As recorded when NegativeSpace first indexed this file.">
                      File modified <span aria-hidden="true">ⓘ</span></span>}>
          {epoch(d.file_modified)}
        </Row>
      </Section>

      <PhotoHistory refreshKey={refreshKey} id={d.id} onLineage={onLineage} />
      {d.thumbnail.availability === "failed" && (
        <p className="muted">Thumbnail unavailable: {d.thumbnail.failure_detail ?? "reason not recorded"}</p>
      )}
      <section className="info-section">
        <h3>Exact duplicates ({d.duplicates.length})</h3>
        {d.duplicates.length === 0 ? (
          <p className="muted info-empty">No other catalogued file has identical content.</p>
        ) : (
          <ul className="copies info">
            {d.duplicates.map((c) => (
              <li key={c.id}>
                <span className="badge">{STATUS[c.status] ?? c.status}</span>
                <FileLocations source={[{label:"Photo",path:c.source_path ?? "—"}]}
                  destination={c.status === "Duplicate" && c.dest_path ? [{label:"Recorded content",path:c.dest_path,note:"From the catalog, not re-checked."}] : []} />
              </li>
            ))}
          </ul>
        )}
      </section>
      <details className="info-section"><summary>Technical details</summary>
      <Section title="Additional file information" note="Recorded file properties and other extracted details. Compare EXIF and XMP in the Metadata tab.">
        <tr className="meta-row"><td colSpan={2}><AllMetadata tags={d.metadata ?? []} /></td></tr>
      </Section>
      <Section title="Fingerprints">
        <Row label="SHA-1"><code>{d.sha1 ?? "not recorded"}</code></Row>
        <Row label="Perceptual hash"><code>{d.phash ?? "not recorded"}</code></Row>
      </Section>
      </details>
    </div>
  );
}

// Additional catalogued photo/file tags, folded until requested (webui-spec 4.2).
// Source-specific values and comparisons live in the separate Metadata tab.
function AllMetadata({ tags }: { tags: [string, unknown][] }) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const f = filter.trim().toLowerCase();
  const shown = f ? tags.filter(([k, v]) => k.toLowerCase().includes(f) || String(v).toLowerCase().includes(f)) : tags;
  const text = (v: unknown) => (v !== null && typeof v === "object" ? JSON.stringify(v) : String(v));
  return (
    <div className="all-metadata">
      {/* Stays at the top of the panel while the tags scroll, so Hide is always at hand. */}
      <div className={open ? "meta-head" : undefined}>
        <button className="link" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Hide file details" : `Show file details (${tags.length} fields)`}
        </button>
        {open && <SearchField placeholder="Filter file details" value={filter} onValueChange={setFilter}
                              aria-label="Filter file details" clearLabel="Clear the filter" />}
      </div>
      {open && (
        <>
          <p className="muted">Recorded file details, including properties calculated by the app. To compare EXIF and XMP, use the Metadata tab.</p>
          {shown.length === 0 ? <p className="muted">No field matches “{filter}”.</p> : (
            <table className="meta-table">
              <tbody>
                {shown.map(([k, v]) => <tr key={k}><th>{k}</th><td>{text(v)}</td></tr>)}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}

const EVENT_LABEL: Record<string, string> = {
  Pending: "Indexed", Duplicate: "Indexed as a duplicate", Processing: "Started", Completed: "Moved",
  Copied: "Copied", Copied_Only: "Copied only, original kept", Failed: "Failed", Removed_Duplicate: "Duplicate removed",
  Found_At_Destination: "Found at destination",
  Skipped: "Skipped", Cancelled: "Cancelled", Renamed: "Renamed",
  Rejected: "Moved to Rejects", Rejected_Copied: "Rejected", Returned: "Returned to library",
  Emptied: "Emptied from Rejects",
};

// The photo's latest events in the panel, compact (webui-spec 4.2); each opens the
// lineage tree, as does View lineage tree. The log is the other way to the full record.
const RECENT = 3;

function PhotoHistory({ id, onLineage, refreshKey }: { id: number; onLineage: () => void; refreshKey: number }) {
  const [page, setPage] = useState<{ items: Operation[]; total: number } | null>(null);
  useEffect(() => {
    let live = true;
    setPage(null);
    api.operations({ run: [], status: [], photo: id, q: "", since: "", until: "" }, 1, RECENT)
      .then((d) => live && setPage(d), () => live && setPage({ items: [], total: 0 }));
    return () => { live = false; };
  }, [id, refreshKey]);
  const events = page ? [...page.items].reverse() : [];
  return (
    <section className="info-section photo-history">
      <h3>History{page && page.total > 0 ? ` (${page.total})` : ""}</h3>
      {!page ? <p className="muted info-empty">Loading…</p> : page.total === 0 ? (
        <p className="muted info-empty">Nothing recorded yet.</p>
      ) : (
        <>
          {page.total > events.length && <p className="muted">The latest {events.length}:</p>}
          <ol className="history-list">
            {events.map((op) => (
              <li key={op.id} className={op.status === "Failed" ? "history-failed" : undefined}>
                <button className="history-event" onClick={onLineage} title="Open the lineage tree">
                  <strong>{operationLabel(op, EVENT_LABEL[op.status] ?? op.status)}</strong>
                  <span className="muted"> · {jobLabel(op.run_id, op.mode)} · {epoch(Date.parse(op.timestamp) / 1000)}</span>
                </button>
              </li>
            ))}
          </ol>
          <div className="history-links">
            <a href={logUrl({ photo: id })} onClick={follow}>Open in the log</a>
            <button className="link" onClick={onLineage}>View lineage tree</button>
          </div>
        </>
      )}
    </section>
  );
}
