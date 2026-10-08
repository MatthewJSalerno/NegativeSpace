import { ReviewNote } from "./ReviewNote";
import { TabList, tabPanel } from "./ui/Tabs";
import type { SetActions } from "./ReviewActions";
import type { ComparisonState } from "../comparisonState";
import { Modal } from "./ui/Modal";
import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { api, ApiError, type PhotoDetail } from "../api";
import { bytes, epoch, isFallbackDate } from "../format";
import { follow, logUrl } from "../nav";
import { LineageDialog } from "./LineageDialog";
import { jobLabel } from "../jobs";
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

const EXIF_DATE_LABEL = { taken: "Date taken", digitized: "Date digitized", modified: "Date modified" };

// The split-screen Inspector (webui-spec 4.2): the grid thumbnail at once, the
// 1024px preview as soon as the engine has made it, and what the catalog records.
// When the panel is dragged wide, the details move to the right of the photo
// and the inner divider adjusts their share of space. Clicking the photo enlarges it over a blurred
// page, with its details below; Esc or the close button returns.
export function Inspector({ id, width, onClose, onStep, onOpenPhoto, jobRunning, refreshKey, matchView, onMatchView, tab, onTab, comparison, onComparison, coveredByDialog = false, setBrowse, onOpenSet, onShowSet, onReject, onReturn, onRejectMatch, onKeep, onNotice, onReviewPhoto }: SetActions & {
  // Reject this photo, or return it from Rejects; each asks first.
  onReject?: (filename: string) => void;
  onReturn?: () => void;
  onReviewPhoto?: () => void;
  // From Similar photos: reject one look-alike, or keep this photo and reject the rest.
  onRejectMatch?: (id: number, filename: string) => void;
  onKeep?: (keep: number, name: string, threshold: number) => void;
  onNotice?: (text: string, actions: { label: string; run: () => void }[], photo?: number) => void;
  coveredByDialog?: boolean;
  comparison: ComparisonState | null;
  onComparison: (state: ComparisonState | null) => void;
  id: number;
  width: number | null;
  onClose: () => void;
  onStep: (delta: number) => void;
  // Opens another photo in the panel: a duplicate, from the lineage tree.
  onOpenPhoto: (id: number) => void;
  jobRunning: boolean;
  refreshKey: number;
  tab: "information" | "similar";
  onTab: (tab: "information" | "similar") => void;
  matchView: MatchView;
  onMatchView: (view: MatchView) => void;
}) {
  const [narrow, setNarrow] = useState(() => window.matchMedia("(max-width: 800px)").matches);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 800px)");
    const update = () => setNarrow(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  const tabId = useId();
  const panel = useRef<HTMLElement>(null);
  const header = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    if (!header.current) return;
    const observer = new ResizeObserver(([entry]) => panel.current?.style.setProperty(
      "--inspector-head-h", `${Math.ceil(entry.target.getBoundingClientRect().height)}px`));
    observer.observe(header.current);
    return () => observer.disconnect();
  }, [narrow]);
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
  }, [narrow]);
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
  const [enlarged, setEnlarged] = useState(false);
  const [lineage, setLineage] = useState(false);
  const inLibrary = !!detail && detail.id === id && IN_LIBRARY.includes(detail.status);
  const canCompare = inLibrary || (!!detail && detail.id === id && IN_REJECTS.includes(detail.status));
  const activeTab = canCompare ? tab : "information";
  useEffect(() => {
    if (detail?.id !== id || canCompare) return;
    if (tab !== "information") onTab("information");
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
      if (e.key === "Escape") (enlarged ? setEnlarged(false) : onClose());
      if (e.key === "ArrowRight") onStep(1);
      if (e.key === "ArrowLeft") onStep(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, onStep, enlarged]);

  const photo = (
    <>
      {!previewReady && <Thumb refreshKey={refreshKey} id={id} alt={detail?.filename ?? ""} />}
      {!previewFailed && (
        <img
          key={id}
          src={api.thumbnailUrl(id, "preview")}
          alt={detail?.filename ?? ""}
          style={{ display: previewReady ? undefined : "none" }}
          onLoad={() => setPreviewReady(true)}
          onError={() => setPreviewFailed(true)}
        />
      )}
    </>
  );

  const body = (
    <section ref={panel} className="inspector" data-tab={activeTab} aria-label="Photo details" style={width ? { flexBasis: `${width}px` } : undefined}>
      <header ref={header} className="inspector-head">
        <button onClick={() => onStep(-1)} aria-label="Previous photo">‹</button>
        <h2 title={detail?.filename}>{detail?.filename ?? "…"}</h2>
        <button onClick={() => onStep(1)} aria-label="Next photo">›</button>
        <button onClick={onClose} aria-label="Close">✕</button>
      </header>
      <div className="inspector-main" data-wide={splitSize.wide}
           style={{ "--preview-share": `${previewShare}%`,
             "--preview-size": `${Math.round(splitSize.height * (splitSize.wide ? 1 : previewShare / 100))}px` } as CSSProperties}>
        <div className="inspector-preview" data-reference={activeTab === "similar"}>
          {activeTab === "similar" && <h3>Reference photo</h3>}
          <button className="inspector-image" onClick={() => setEnlarged(true)} aria-label="Enlarge the photo"
                  title="Click to enlarge">
            {photo}
          </button>
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
        <div className="inspector-side">
          {error && <p className="error">{error}</p>}
          <TabList className="inspector-tabs" label="Photo inspector" idBase={tabId} value={activeTab} onChange={onTab}
            tabs={canCompare ? [{ value: "information", label: inLibrary ? "Photo information" : "File information" }, { value: "similar", label: inLibrary ? "Similar photos" : "Similar photos in Library" }] : [{ value: "information", label: "File information" }]} />
          <div className="inspector-tab-panel" role="tabpanel" {...tabPanel(tabId, "information", activeTab)}>
            {detail && activeTab === "information" && <Details refreshKey={refreshKey} detail={detail} onLineage={() => setLineage(true)}
              review={inLibrary ? <ReviewNote key={id} id={id} refreshKey={refreshKey} disabled={jobRunning} compact onOpenReview={onReviewPhoto}
                concerns={detail.date_warning ? [{label:"Suspicious date",message:`${detail.date_warning} Date editing is not available yet.`}]
                  : !detail.exif_dates?.some(d => d.field === "taken") ? [{label:"No capture date",message:"No date taken is recorded in the photo’s EXIF."}] : []}
                actions={IN_LIBRARY.includes(detail.status) && onReject
                  ? <button onClick={() => onReject(detail.filename)} disabled={jobRunning} title={jobRunning ? "Wait for the running job to finish." : "Move this photo to Rejects. Nothing is deleted."}>Reject…</button>
                  : null} /> : IN_REJECTS.includes(detail.status) && onReturn ? <div className="photo-actions"><button onClick={onReturn} disabled={jobRunning} title={jobRunning ? "Wait for the running job to finish." : undefined}>Return to library…</button></div> : null} />}
          </div>
          <div className="inspector-tab-panel" role="tabpanel" {...tabPanel(tabId, "similar", activeTab)}>
            {detail && activeTab === "similar" && <div className="inspector-body"><PhotoMatches key={id} id={id} name={detail.filename}
              jobRunning={jobRunning} onReject={onRejectMatch ? (photo) => onRejectMatch(photo.id, photo.filename) : undefined}
              onKeep={inLibrary && onKeep ? (threshold) => onKeep(id, detail.filename, threshold) : undefined}
              delivered={canCompare} rejected={!inLibrary}
              view={matchView} onView={onMatchView} refreshKey={refreshKey}
              onReview={openComparison} changes={comparisonChanges} /></div>}
          </div>
        </div>
      </div>
      {lineage && detail && createPortal(
        <LineageDialog photoId={id} filename={detail.filename} jobRunning={jobRunning}
                       onOpenPhoto={(other) => { setLineage(false); onOpenPhoto(other); }} onClose={() => setLineage(false)} />,
        document.body)}
      {/* Rendered at the page's top level: inside the Inspector, a size container,
          position: fixed would be relative to the panel and stay under the toolbar. */}
      {enlarged && createPortal(
        <Modal className="lightbox" label={`Enlarged: ${detail?.filename ?? ""}`} onClose={() => setEnlarged(false)}>
          <button className="lightbox-close" onClick={() => setEnlarged(false)} aria-label="Close the enlarged photo">✕</button>
          <div className="lightbox-body">
            <div className="lightbox-image">{photo}</div>
            {detail && <Details refreshKey={refreshKey} detail={detail} onLineage={() => setLineage(true)} />}
          </div>
        </Modal>,
        document.body,
      )}
    </section>
  );
  return <>
    {narrow && comparison == null && !coveredByDialog ? <Modal deferWhileCovered className="mobile-inspector" label="Photo details" onClose={onClose}>{body}</Modal> : body}
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

function exifTime(value: string) {
  // EXIF writes "2021:05:01 10:00:00"; show the date with dashes, the time as recorded.
  const [date, time = ""] = value.split(" ");
  return `${date.replace(/:/g, "-")} ${time}`.trim();
}

function Details({ detail: d, onLineage, refreshKey, review }: { detail: PhotoDetail; onLineage: () => void; refreshKey: number; review?: ReactNode }) {
  const fallback = isFallbackDate(d.date_source);
  const exposure = [d.iso != null ? `ISO ${d.iso}` : null, d.aperture != null ? `f/${d.aperture}` : null,
                    d.shutter != null ? `${d.shutter}s` : null].filter(Boolean).join(" · ");
  // Time zones: EXIF records one per date only when the camera wrote an offset tag.
  // If none did, one note covers them all; if only some did, the others get an asterisk.
  const dates = d.exif_dates ?? [];
  const withZone = dates.filter((x) => x.offset).length;
  const mixed = withZone > 0 && withZone < dates.length;
  const zoneNote = dates.length === 0 ? null
    : withZone === 0 ? "Times are as the camera recorded them; it recorded no time zone."
    : mixed ? "* No time zone recorded for this time; it is shown as the camera recorded it."
    : null;
  const taken = dates.find((x) => x.field === "taken");
  return (
    <div className="inspector-body">
      {review}
      {!review && IN_LIBRARY.includes(d.status) && d.date_warning && <p className="section-note"><strong>Suspicious date:</strong> {d.date_warning} Recorded value: {d.date_taken}. Source: {fallback ? "file modification fallback" : d.date_source === "exif" ? "photo EXIF" : d.date_source ?? "unknown"}. Check the recorded metadata or compare similar photos for clues. The value is unchanged; date editing is not yet available. <a href="/?view=suspicious">View suspicious dates</a></p>}
      {IN_LIBRARY.includes(d.status) && d.visual_issue && <p className="section-note"><strong>Visual matching unavailable:</strong> {d.visual_issue} The catalogued file is retained. Missing EXIF alone is not evidence of damage.</p>}
      {d.status === "Failed" && <p className="notice"><strong>File needs attention.</strong> Processing failed; this file is not in Library. Check the recorded reason and fix the source file or its access outside the app. <a href={logUrl({photo:d.id,status:"Failed"})} onClick={follow}>View failure details</a></p>}
      <Section title="File">
        <Row label="Status">{STATUS[d.status] ?? d.status}</Row>
        <Row label={d.dest_path_is_projection ? "Proposed destination path" : "Destination path"}>
          <code>{d.dest_path ?? "—"}</code>
          {d.dest_path_is_projection && <div className="muted">Not written yet.</div>}
          {d.has_collision_rename && <div className="muted">Renamed: another file already had this name.</div>}
        </Row>
        <Row label="Source path"><code>{d.source_path ?? "—"}</code></Row>
        <Row label="Size">{bytes(d.file_size)}{d.width && d.height ? ` · ${d.width} × ${d.height}` : ""}</Row>
        <Row label={<span className="row-tip" title="As recorded when NegativeSpace first indexed this file.">
                      File modified <span aria-hidden="true">ⓘ</span></span>}>
          {epoch(d.file_modified)}
          {fallback && <div className="muted">* Files it under Undated: no EXIF date taken.</div>}
        </Row>
      </Section>
      <Section title="Photo EXIF information" note={zoneNote}>
        {!taken && <Row label="Date taken"><span className="muted">Not in the photo's EXIF</span></Row>}
        {dates.map((x) => (
          <Row key={x.field} label={<>{EXIF_DATE_LABEL[x.field]}{mixed && !x.offset ? " *" : ""}</>}>
            {exifTime(x.value)}{x.offset ? ` (UTC${x.offset})` : ""}
          </Row>
        ))}
        <Row label="Camera">{d.camera ?? <span className="muted">Not recorded</span>}</Row>
        <Row label="Exposure">{exposure || <span className="muted">Not recorded</span>}</Row>
        <tr className="meta-row"><td colSpan={2}><AllMetadata tags={d.metadata ?? []} /></td></tr>
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
                <code>{c.source_path}</code>
                {c.status === "Duplicate" && c.dest_path && (
                  <div className="muted">Its content is recorded at <code>{c.dest_path}</code> (from the catalog, not re-checked).</div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
      <Section title="Fingerprints">
        <Row label="SHA-1"><code>{d.sha1 ?? "not recorded"}</code></Row>
        <Row label="Perceptual hash"><code>{d.phash ?? "not recorded"}</code></Row>
      </Section>
    </div>
  );
}

// Every tag the Index recorded, folded until asked for under the EXIF fields it
// extends (webui-spec 4.2): those fields are a few of them. Read from the catalog, so it is the photo as last indexed.
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
          {open ? "Hide all metadata" : `Show all metadata (${tags.length} tags)`}
        </button>
        {open && <SearchField placeholder="Filter tags" value={filter} onValueChange={setFilter}
                              aria-label="Filter the metadata" clearLabel="Clear the filter" />}
      </div>
      {open && (
        <>
          <p className="muted">Every tag recorded when the photo was last indexed, including the ones above.</p>
          {shown.length === 0 ? <p className="muted">No tag matches “{filter}”.</p> : (
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
  const [page, setPage] = useState<{ items: { id: number; run_id: number; mode: string | null; status: string; timestamp: string }[]; total: number } | null>(null);
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
                  <strong>{EVENT_LABEL[op.status] ?? op.status}</strong>
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
