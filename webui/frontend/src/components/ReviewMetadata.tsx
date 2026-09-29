import { useEffect, useState } from "react";
import { api, type PhotoDetail } from "../api";
import { photoDate } from "../format";

const valueText = (value: unknown): string => value == null || value === "" ? "Not recorded"
  : typeof value === "object" ? JSON.stringify(value) : String(value);

export function ReviewMetadata({ reference, candidate, refreshKey }: { reference: number; candidate: number; refreshKey: number }) {
  const [details, setDetails] = useState<[PhotoDetail, PhotoDetail] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [allTags, setAllTags] = useState(false);
  const [differences, setDifferences] = useState(false);
  const [filter, setFilter] = useState("");
  useEffect(() => {
    let live = true;
    setDetails(null); setError(null);
    Promise.all([api.inspect(reference), api.inspect(candidate)]).then(
      (data) => { if (live) setDetails(data); },
      (e) => { if (live) setError(e instanceof Error ? e.message : "Metadata could not be loaded."); });
    return () => { live = false; };
  }, [reference, candidate, refreshKey, retry]);
  const date = (d: PhotoDetail) => d.date_taken ? `${photoDate(d.date_taken)}${d.date_offset ? ` ${d.date_offset}` : " · timezone unknown"}${d.date_source === "file_mtime" ? " (file modification fallback)" : ""}` : null;
  const dateSource = (d: PhotoDetail) => d.date_source === "file_mtime" ? "File modification time"
    : d.date_source === "exif" ? "Photo EXIF" : d.date_source;
  const rows: [string, unknown, unknown][] = details ? allTags
    ? [...new Set(details.flatMap(d => d.metadata.map(([key]) => key)))].sort().map(key =>
      [key, details[0].metadata.find(([k]) => k === key)?.[1], details[1].metadata.find(([k]) => k === key)?.[1]])
    : [
      ["Recorded date", ...details.map(date)],
      ["Date source", ...details.map(dateSource)],
      ["Camera", ...details.map(d => d.camera)],
      ["ISO", ...details.map(d => d.iso)],
      ["Aperture", ...details.map(d => d.aperture)],
      ["Shutter", ...details.map(d => d.shutter)],
    ] as [string, unknown, unknown][] : [];
  const shown = rows.filter(([key, a, b]) => (!differences || valueText(a) !== valueText(b)) && (!allTags || key.toLowerCase().includes(filter.toLowerCase())));
  return <section className="review-metadata" aria-label="Metadata comparison">
    <h3>Compare information</h3>
    <p className="section-note">Values recorded at the last index. A visual match does not establish a shared date or location.</p>
    <label><input type="checkbox" checked={allTags} onChange={e => setAllTags(e.target.checked)} />All recorded tags</label>
    <label><input type="checkbox" checked={differences} onChange={e => setDifferences(e.target.checked)} />Differences only</label>
    {allTags && <input type="search" aria-label="Find metadata field" placeholder="Find a field" value={filter} onChange={e => setFilter(e.target.value)} />}
    {error ? <p className="error" role="alert">{error} <button onClick={() => setRetry(n => n + 1)}>Retry metadata</button></p>
      : !details ? <p role="status">Loading metadata…</p> : <>
        <table className="review-metadata-table"><thead><tr><th>Field</th><th>Reference</th><th>Candidate</th></tr></thead>
          <tbody>{shown.map(([key, a, b]) => <tr key={key} data-different={valueText(a) !== valueText(b)}>
            <th scope="row">{key}{valueText(a) !== valueText(b) && <small>Different</small>}</th><td>{valueText(a)}</td><td>{valueText(b)}</td>
          </tr>)}</tbody></table>
        {shown.length === 0 && <p>No fields match these filters.</p>}
      </>}
  </section>;
}
