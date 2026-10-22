import { follow } from "../nav";
import type { Discovery } from "../api";
import { count, plural } from "../format";

/** The same immutable Index walk in the summary and the expanded job log. */
export function DiscoverySummary({ data, runId }: { data: Discovery | null | undefined; runId?: number | null }) {
  if (!data) return null;
  const types = (values: Record<string, number>) => Object.entries(values).sort(([a], [b]) => a.localeCompare(b))
    .map(([ext, n]) => <li key={ext}>{ext ? ext.slice(1).toUpperCase() : "No extension"}: {count(n)}</li>);
  return <details className="discovery-summary">
    <summary>By file type</summary>
    <p>{plural(data.files_found, "file")} found in this Index walk. Counts use file extensions; they do not mean every file was readable or organized.</p>
    {data.partial && <p className="warning">The walk could not read {plural(data.unreadable, "folder or entry", "folders or entries")}. These counts are incomplete. {runId != null && <a href={`/logs?run=${runId}`} onClick={follow}>View Index log</a>}</p>}
    <h4>Selected photo types ({count(data.eligible)})</h4>
    {data.eligible ? <ul>{types(data.photos)}</ul> : <p>No selected photo types found.</p>}
    {Object.keys(data.disabled_photos).length > 0 && <>
      <h4>Photo types turned off</h4><ul>{types(data.disabled_photos)}</ul>
      <p><button className="link" onClick={() => window.dispatchEvent(new Event("ns-review-settings"))}>Change in Settings → Files</button></p>
    </>}
    <p>{plural(data.sidecars, "sidecar")} · {plural(data.videos, "video")}</p>
    <p>{plural(data.other, "other file")}, left untouched</p>
    <p className="section-note">Sidecar counts cover XMP, AAE and THM files. Videos and other unselected files stay in the source. This record does not change after Copy, Move or a settings change.</p>
  </details>;
}
