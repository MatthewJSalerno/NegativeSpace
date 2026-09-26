import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { api, ApiError, type PhotoDetail } from "../api";
import { bytes, epoch, isFallbackDate } from "../format";
import { follow, logUrl } from "../nav";
import { Thumb } from "./Thumb";

const STATUS: Record<string, string> = {
  Pending: "Not yet organized", Processing: "In progress", Completed: "Moved to the destination",
  Copied: "Copied to the destination", Failed: "Failed", Duplicate: "Duplicate (source still on disk)",
  Removed_Duplicate: "Duplicate (source removed)", Found_At_Destination: "Found at the destination",
};

const EXIF_DATE_LABEL = { taken: "Date taken", digitized: "Date digitized", modified: "Date modified" };

// The split-screen Inspector (webui-spec 4.2): the grid thumbnail at once, the
// 1024px preview as soon as the engine has made it, and what the catalog records.
// When the panel is dragged wide, the details move to the right of the photo
// (a container query in styles.css). Clicking the photo enlarges it over a blurred
// page, with its details below; Esc or the close button returns.
export function Inspector({ id, width, onClose, onStep }: {
  id: number;
  width: number | null;
  onClose: () => void;
  onStep: (delta: number) => void;
}) {
  const [detail, setDetail] = useState<PhotoDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [previewReady, setPreviewReady] = useState(false);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [enlarged, setEnlarged] = useState(false);

  useEffect(() => {
    let live = true;
    setDetail(null);
    setError(null);
    setPreviewReady(false);
    setPreviewFailed(false);
    api.inspect(id).then(
      (d) => live && setDetail(d),
      (e) => live && setError(e instanceof ApiError ? e.message : "The photo could not be loaded."),
    );
    return () => {
      live = false;
    };
  }, [id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest("input, textarea, select")) return;
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
      {!previewReady && <Thumb id={id} alt={detail?.filename ?? ""} />}
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

  return (
    <section className="inspector" aria-label="Photo details" style={width ? { flexBasis: `${width}px` } : undefined}>
      <header className="inspector-head">
        <button onClick={() => onStep(-1)} aria-label="Previous photo">‹</button>
        <h2 title={detail?.filename}>{detail?.filename ?? "…"}</h2>
        <button onClick={() => onStep(1)} aria-label="Next photo">›</button>
        <button onClick={onClose} aria-label="Close">✕</button>
      </header>
      <div className="inspector-main">
        <button className="inspector-image" onClick={() => setEnlarged(true)} aria-label="Enlarge the photo"
                title="Click to enlarge">
          {photo}
        </button>
        <div className="inspector-side">
          {error && <p className="error">{error}</p>}
          {detail && <Details detail={detail} />}
        </div>
      </div>
      {/* Rendered at the page's top level: inside the Inspector, a size container,
          position: fixed would be relative to the panel and stay under the toolbar. */}
      {enlarged && createPortal(
        <div className="lightbox" role="dialog" aria-modal="true" aria-label={`Enlarged: ${detail?.filename ?? ""}`}
             onMouseDown={(e) => e.target === e.currentTarget && setEnlarged(false)}>
          <button className="lightbox-close" onClick={() => setEnlarged(false)} aria-label="Close the enlarged photo">✕</button>
          <div className="lightbox-body">
            <div className="lightbox-image">{photo}</div>
            {detail && <Details detail={detail} />}
          </div>
        </div>,
        document.body,
      )}
    </section>
  );
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

function Details({ detail: d }: { detail: PhotoDetail }) {
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
      <Section title="File">
        <Row label="Status">{STATUS[d.status] ?? d.status}</Row>
        <Row label={d.dest_path_is_projection ? "Proposed destination path" : "Destination path"}>
          <code>{d.dest_path ?? "—"}</code>
          {d.dest_path_is_projection && <div className="muted">Not written yet.</div>}
          {d.has_collision_rename && <div className="muted">Renamed: another file already had this name.</div>}
        </Row>
        <Row label="Source path"><code>{d.source_path ?? "—"}</code></Row>
        <Row label="Size">{bytes(d.file_size)}{d.width && d.height ? ` · ${d.width} × ${d.height}` : ""}</Row>
        <Row label="File modified">
          {epoch(d.file_modified)}
          <div className="muted">
            As recorded when NegativeSpace first indexed this file.{fallback ? " The photo's EXIF has no date taken, so this files it under Undated." : ""}
          </div>
        </Row>
      </Section>
      <PhotoHistory id={d.id} />
      <Section title="Photo EXIF information" note={zoneNote}>
        {!taken && <Row label="Date taken"><span className="muted">Not in the photo's EXIF</span></Row>}
        {dates.map((x) => (
          <Row key={x.field} label={<>{EXIF_DATE_LABEL[x.field]}{mixed && !x.offset ? " *" : ""}</>}>
            {exifTime(x.value)}{x.offset ? ` (UTC${x.offset})` : ""}
          </Row>
        ))}
        <Row label="Camera">{d.camera ?? <span className="muted">Not recorded</span>}</Row>
        <Row label="Exposure">{exposure || <span className="muted">Not recorded</span>}</Row>
      </Section>

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
      <AllMetadata tags={d.metadata ?? []} />
    </div>
  );
}

// Every tag the Index recorded, folded until asked for (webui-spec 4.2): the fields
// above are a few of them. Read from the catalog, so it is the photo as last indexed.
function AllMetadata({ tags }: { tags: [string, unknown][] }) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const f = filter.trim().toLowerCase();
  const shown = f ? tags.filter(([k, v]) => k.toLowerCase().includes(f) || String(v).toLowerCase().includes(f)) : tags;
  const text = (v: unknown) => (v !== null && typeof v === "object" ? JSON.stringify(v) : String(v));
  return (
    <section className="info-section all-metadata">
      {/* Stays at the top of the panel while the tags scroll, so Hide is always at hand. */}
      <div className={open ? "meta-head" : undefined}>
        <button className="link" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Hide all metadata" : `Show all metadata (${tags.length} tags)`}
        </button>
        {open && <input type="search" placeholder="Filter tags" value={filter} onChange={(e) => setFilter(e.target.value)}
                        aria-label="Filter the metadata" />}
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
    </section>
  );
}

const EVENT_LABEL: Record<string, string> = {
  Pending: "Indexed", Duplicate: "Indexed as a duplicate", Processing: "Started", Completed: "Moved",
  Copied: "Copied", Failed: "Failed", Removed_Duplicate: "Duplicate removed", Found_At_Destination: "Found at destination",
  Skipped: "Skipped", Cancelled: "Cancelled", Renamed: "Renamed",
};

// Everything recorded for the photo, in the panel itself (webui-spec 4.2), oldest first:
// a photo has a handful of events, so the pane shows them all. The log has the same
// entries with its filters and export, one link away.
const HISTORY_MAX = 200;

function PhotoHistory({ id }: { id: number }) {
  const [page, setPage] = useState<{ items: { id: number; run_id: number; mode: string | null; status: string; timestamp: string;
                                              error_message: string | null }[]; total: number } | null>(null);
  useEffect(() => {
    let live = true;
    setPage(null);
    api.operations({ run: [], status: [], photo: id, q: "", since: "", until: "" }, 1, HISTORY_MAX)
      .then((d) => live && setPage(d), () => live && setPage({ items: [], total: 0 }));
    return () => { live = false; };
  }, [id]);
  const events = page ? [...page.items].reverse() : [];
  return (
    <section className="info-section photo-history">
      <h3>History{page && page.total > 0 ? ` (${page.total})` : ""}</h3>
      {!page ? <p className="muted info-empty">Loading…</p> : page.total === 0 ? (
        <p className="muted info-empty">Nothing recorded yet.</p>
      ) : (
        <>
          <ol className="history-list">
            {events.map((op) => (
              <li key={op.id} className={op.status === "Failed" ? "history-failed" : undefined}>
                <strong>{EVENT_LABEL[op.status] ?? op.status}</strong>
                <span className="muted"> · job #{op.run_id}{op.mode ? ` ${op.mode.toLowerCase()}` : ""} · {epoch(Date.parse(op.timestamp) / 1000)}</span>
                {op.error_message && <div className="history-detail">{op.error_message}</div>}
              </li>
            ))}
          </ol>
          {page.total > events.length && <p className="muted">Showing the newest {events.length} of {page.total}.</p>}
          <a className="history-open" href={logUrl({ photo: id })} onClick={follow}>Open in the log</a>
        </>
      )}
    </section>
  );
}
