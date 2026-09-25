import { useEffect, useState, type ReactNode } from "react";
import { api, ApiError, type PhotoDetail } from "../api";
import { bytes, epoch, isFallbackDate, photoDate } from "../format";
import { Thumb } from "./Thumb";

const STATUS: Record<string, string> = {
  Pending: "Not yet organized", Processing: "In progress", Completed: "Moved to the destination",
  Copied: "Copied to the destination", Failed: "Failed", Duplicate: "Duplicate (source still on disk)",
  Removed_Duplicate: "Duplicate (source removed)", Found_At_Destination: "Found at the destination",
};

// The split-screen Inspector (webui-spec 4.2): the grid thumbnail at once, the
// 1024px preview as soon as the engine has made it, and what the catalog records.
// When the panel is dragged wide, the details move to the right of the photo
// (a container query in styles.css), so a large preview does not push them away.
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
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") onStep(1);
      if (e.key === "ArrowLeft") onStep(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, onStep]);

  return (
    <section className="inspector" aria-label="Photo details" style={width ? { flexBasis: `${width}px` } : undefined}>
      <header className="inspector-head">
        <button onClick={() => onStep(-1)} aria-label="Previous photo">‹</button>
        <h2 title={detail?.filename}>{detail?.filename ?? "…"}</h2>
        <button onClick={() => onStep(1)} aria-label="Next photo">›</button>
        <button onClick={onClose} aria-label="Close">✕</button>
      </header>
      <div className="inspector-main">
      <div className="inspector-image">
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
      </div>
      <div className="inspector-side">
        {error && <p className="error">{error}</p>}
        {detail && <Details detail={detail} />}
      </div>
      </div>
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <tr>
      <th scope="row">{label}</th>
      <td>{children}</td>
    </tr>
  );
}

// One bordered table per section; every table has the same width and label column.
function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="info-section">
      <h3>{title}</h3>
      <table className="info">
        <tbody>{children}</tbody>
      </table>
    </section>
  );
}

function Details({ detail: d }: { detail: PhotoDetail }) {
  const fallback = isFallbackDate(d.date_source);
  const exposure = [d.iso != null ? `ISO ${d.iso}` : null, d.aperture != null ? `f/${d.aperture}` : null,
                    d.shutter != null ? `${d.shutter}s` : null].filter(Boolean).join(" · ");
  return (
    <div className="inspector-body">
      <Section title="File">
        <Row label="Status">{STATUS[d.status] ?? d.status}</Row>
        <Row label={d.dest_path_is_projection ? "Will go to" : "At destination"}>
          <code>{d.dest_path ?? "—"}</code>
          {d.dest_path_is_projection && <div className="muted">Planned location; not written yet.</div>}
          {d.has_collision_rename && <div className="muted">Renamed: another file already had this name.</div>}
        </Row>
        <Row label="From source"><code>{d.source_path ?? "—"}</code></Row>
        <Row label="Size">{bytes(d.file_size)}{d.width && d.height ? ` · ${d.width} × ${d.height}` : ""}</Row>
        <Row label="File created">
          {d.file_created != null ? epoch(d.file_created) : <span className="muted">Not reported by the storage</span>}
        </Row>
        <Row label="File modified">
          {epoch(d.file_modified)}
          <div className="muted">
            As first scanned.{fallback ? " The photo's EXIF has no date taken, so this files it under Undated." : ""}
          </div>
        </Row>
      </Section>
      <Section title="Photo EXIF information">
        <Row label="Date taken">
          {fallback ? <span className="muted">Not in the photo's EXIF</span> : (
            <>
              {photoDate(d.date_taken)}
              {d.date_offset ? ` (UTC${d.date_offset})` : " (time zone unknown)"}
            </>
          )}
        </Row>
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
    </div>
  );
}
