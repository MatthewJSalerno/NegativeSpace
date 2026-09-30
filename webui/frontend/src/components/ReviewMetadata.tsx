import { useEffect, useState } from "react";
import { api, type PhotoDetail } from "../api";
import { bytes, count, photoDate } from "../format";

const valueText = (value: unknown): string => value == null || value === "" ? "Not recorded"
  : typeof value === "object" ? JSON.stringify(value) : String(value);
type ComparisonRow = { label: string; values: [unknown, unknown]; format?: (value: unknown) => string };
const differs = (row: ComparisonRow) => valueText(row.values[0]) !== valueText(row.values[1]);
const dimensionsKnown = (d: PhotoDetail) => d.width != null && d.height != null && d.width > 0 && d.height > 0;
const extension = (d: PhotoDetail) => /\.([^.]+)$/.exec(d.filename)?.[1].toUpperCase() ?? null;
function fileFormat(d: PhotoDetail): string | null {
  const recorded = d.metadata.find(([key]) => key === "FileType" || key === "File:FileType")?.[1];
  if (typeof recorded === "string" && recorded.trim()) return recorded.trim().toUpperCase();
  const ext = extension(d);
  return ext ? `${ext} (extension only)` : null;
}
function aspectRatio(d: PhotoDetail): string | null {
  if (!dimensionsKnown(d)) return null;
  let a = d.width!, b = d.height!;
  while (b) [a, b] = [b, a % b];
  return `${d.width! / a}:${d.height! / a}`;
}
function ComparisonTable({ title, rows, differences }: { title: string; rows: ComparisonRow[]; differences: boolean }) {
  const shown = rows.filter(row => !differences || differs(row));
  return <div className="review-comparison-section">
    <table className="review-metadata-table">
      <caption>{title}</caption>
      <thead><tr><th scope="col">Field</th><th scope="col">Reference</th><th scope="col">Candidate</th></tr></thead>
      <tbody>{shown.map(row => <tr key={row.label} data-different={differs(row)}>
        <th scope="row">{row.label}{differs(row) && <small>Different</small>}</th>
        {row.values.map((value, i) => <td key={i}>{value == null || value === "" ? "Not recorded" : row.format ? row.format(value) : valueText(value)}</td>)}
      </tr>)}</tbody>
    </table>
    {shown.length === 0 && <p className="section-note">No fields match these filters.</p>}
  </div>;
}

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
  const row = (label: string, value: (d: PhotoDetail) => unknown, format?: ComparisonRow["format"]): ComparisonRow =>
    ({ label, values: details ? [value(details[0]), value(details[1])] : [null, null], format });
  const fileRows = [
    row("Format", fileFormat),
    row("Extension", d => extension(d) ? `.${extension(d)}` : null),
    row("Pixel dimensions", d => dimensionsKnown(d) ? `${count(d.width!)} × ${count(d.height!)}` : null),
    row("Megapixels", d => dimensionsKnown(d) ? d.width! * d.height! : null,
      v => (Number(v) < 10000 ? "<0.01" : (Number(v) / 1e6).toLocaleString(undefined, { maximumFractionDigits: 2 })) + " MP"),
    row("File size", d => d.file_size, v => `${bytes(Number(v))}${Number(v) >= 1000 ? ` (${count(Number(v))} bytes)` : ""}`),
    row("Aspect ratio", aspectRatio),
  ];
  const captureRows = [row("Recorded date", date), row("Date source", dateSource),
    ...(details?.some(d => d.date_warning) ? [row("Date review", d => d.date_warning ?? "No date warning")] : []), row("Camera", d => d.camera),
    row("ISO", d => d.iso), row("Aperture", d => d.aperture), row("Shutter", d => d.shutter)];
  const tagRows: ComparisonRow[] = details && allTags
    ? [...new Set(details.flatMap(d => d.metadata.map(([key]) => key)))].sort()
      .filter(key => key.toLowerCase().includes(filter.toLowerCase()))
      .map(key => row(key, d => d.metadata.find(([k]) => k === key)?.[1])) : [];
  return <section className="review-metadata" aria-label="Metadata comparison">
    <h3>Compare information</h3>
    <p className="section-note">Values recorded at the last index. Larger dimensions or file size do not guarantee better quality.</p>
    <label><input type="checkbox" checked={differences} onChange={e => setDifferences(e.target.checked)} />Differences only</label>
    {error ? <p className="error" role="alert">{error} <button onClick={() => setRetry(n => n + 1)}>Retry metadata</button></p>
      : !details ? <p role="status">Loading metadata…</p> : <>
        <ComparisonTable title="File and image properties" rows={fileRows} differences={differences} />
        <ComparisonTable title="Capture information" rows={captureRows} differences={differences} />
        <p className="section-note">A visual match does not establish a shared date or location.</p>
        <label><input type="checkbox" checked={allTags} onChange={e => setAllTags(e.target.checked)} />All recorded tags</label>
        {allTags && <>
          <input type="search" aria-label="Find metadata field" placeholder="Find a field" value={filter} onChange={e => setFilter(e.target.value)} />
          <ComparisonTable title="All recorded metadata" rows={tagRows} differences={differences} />
        </>}
      </>}
  </section>;
}
