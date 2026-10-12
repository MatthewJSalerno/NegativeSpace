import { useEffect, useId, useState } from "react";
import { api, type MetadataView } from "../api";
import { TabList, tabPanel } from "./ui/Tabs";
import { logUrl, follow } from "../nav";
import { SearchField } from "./ui/SearchField";

const LABELS: Record<string, string> = { date_taken: "Date taken", orientation: "Orientation", camera_make: "Camera make", camera_model: "Camera model", title: "Title", caption: "Caption", keywords: "Keywords", rating: "Rating", creators: "Creators", rights: "Copyright", gps: "Location" };
const own = (values: Record<string, unknown>, key: string) => Object.prototype.hasOwnProperty.call(values, key);
function stable(value: unknown): string {
  if (Array.isArray(value)) return JSON.stringify(value.map(stable));
  if (value !== null && typeof value === "object") return JSON.stringify(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => [k, stable(v)]));
  return JSON.stringify(value);
}
// Plain default-language text and its XMP language wrapper mean the same value.
// Keep additional languages, missing fields, arrays and date precision distinct.
function comparable(value: unknown, key: string) {
  return ["title", "caption", "rights"].includes(key) && typeof value === "string"
    ? { "x-default": value } : value;
}
function display(values: Record<string, unknown>, key: string) {
  if (!own(values, key)) return "Not recorded";
  const value = values[key];
  if (value === null || value === "" || (typeof value === "object" && Object.keys(value).length === 0)) return "Empty";
  return typeof value === "string" ? (key === "date_taken" ? value.replace("T", " ") : value) : JSON.stringify(value);
}
export function MetadataSources({ photoId, refreshKey }: { photoId: number; refreshKey: number }) {
  const [data, setData] = useState<MetadataView | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState("");
  const [compare, setCompare] = useState(false);
  const [differences, setDifferences] = useState(false);
  const [query, setQuery] = useState("");
  const id = useId();
  useEffect(() => {
    let current = true;
    setData(null); setError("");
    api.metadata(photoId).then(value => {
      if (!current) return;
      setData(value); setSelected(value.primary_id ?? "exif");
      setCompare(false); setDifferences(false); setQuery("");
    }).catch(e => { if (current) setError(String(e.message ?? e)); });
    return () => { current = false; };
  }, [photoId, refreshKey, retry]);
  if (error) return <section className="info-section metadata-sources"><h3>Metadata sources</h3><p className="error">{error}</p><button onClick={() => setRetry(x => x + 1)}>Retry metadata</button></section>;
  if (!data) return <section className="info-section metadata-sources" aria-busy="true"><h3>Metadata sources</h3><p className="muted">Loading metadata sources…</p></section>;
  const primary = data.sources.find(s => s.id === data.primary_id);
  const source = data.sources.find(s => s.id === selected) ?? data.sources[0];
  const kind = source.kind;
  const kinds = ["sidecar_xmp", "embedded_xmp", "embedded_exif"];
  const choices = data.sources.filter(s => s.kind === kind);
  const comparing = compare && !!primary && source.id !== primary.id && primary.available && source.available;
  const fields = [...new Set([...Object.keys(source.fields), ...(comparing ? Object.keys(primary.fields) : [])])].sort((a, b) => a === "date_taken" ? -1 : b === "date_taken" ? 1 : a.localeCompare(b));
  const differs = (key: string) => !!primary && (own(source.fields, key) !== own(primary.fields, key) || stable(comparable(source.fields[key], key)) !== stable(comparable(primary.fields[key], key)));
  const shown = fields.filter(k => (!comparing || !differences || differs(k)) && `${LABELS[k] ?? k} ${display(source.fields,k)} ${comparing ? display(primary.fields,k) : ""}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="info-section metadata-sources">
    <h3>Metadata sources</h3>
    <p className="section-note">Recorded metadata. Viewing and comparing leave files and the primary source unchanged.</p>
    {data.notice && <p className="section-note">{data.notice}</p>}
    {data.issues.length > 0 && <p className="notice">Metadata needs attention: {data.issues.map(i => i.detail || i.code.replaceAll("_", " ")).join("; ")} <a href={logUrl({photo:photoId})} onClick={follow}>View photo logs</a></p>}
    <TabList label="Metadata sources" idBase={id} value={kind} className="inspector-tabs" onChange={next => {
      const target = data.sources.find(s => s.kind === next && s.id === data.primary_id) ?? data.sources.find(s => s.kind === next)!;
      setSelected(target.id); setQuery("");
    }} tabs={kinds.map(k => ({ value:k, label:<>{k === "sidecar_xmp" ? "XMP Sidecar" : k === "embedded_xmp" ? "Embedded XMP" : "EXIF"}{primary?.kind === k && <> <span className="badge">Primary</span></>}</> }))} />
    <div role="tabpanel" {...tabPanel(id, kind, kind)}>
      {choices.length > 1 && <label>Sidecar version <select value={source.id} onChange={e => setSelected(e.target.value)}>{choices.map((s, i) => <option key={s.id} value={s.id}>{s.version_id != null ? `Version ${s.version_id}` : `Unreadable sidecar ${i + 1}`}{s.id === data.primary_id ? " · Primary" : " · Alternative"}</option>)}</select></label>}
      {source.issues.map((issue, i) => <p key={i} className="notice">{issue.detail || issue.code.replaceAll("_", " ")}</p>)}
      {!source.available ? <p className="muted">{source.issues.length ? "This source could not be interpreted. See the recorded issue and photo logs." : "No metadata recorded for this source."}</p> : <>
        <div className="metadata-source-options">
          <label className="checkbox-row" style={{ visibility: primary?.available && primary.id !== source.id ? undefined : "hidden" }}><input type="checkbox" disabled={!primary?.available || primary.id === source.id} checked={compare} onChange={e => setCompare(e.target.checked)} />Compare with primary</label>
          <label className="checkbox-row" style={{ visibility: comparing ? undefined : "hidden" }}><input type="checkbox" disabled={!comparing} checked={differences} onChange={e => setDifferences(e.target.checked)} />Show differences only</label>
        </div>
        <SearchField placeholder="Filter fields" value={query} onValueChange={setQuery} aria-label="Filter source fields" clearLabel="Clear source field filter" />
        {fields.includes("date_taken") && <p className="section-note">Dates are shown as recorded; no time zone is assumed.</p>}
        <table className="review-metadata-table"><caption>{comparing ? `${source.label} compared with ${primary.label}` : source.label}</caption><thead><tr><th scope="col">Field</th>{comparing && <th scope="col">Primary value</th>}<th scope="col">{comparing ? "This source" : "Value"}</th></tr></thead><tbody>
          {shown.map(k => <tr key={k} data-different={comparing && differs(k)}><th scope="row">{LABELS[k] ?? k}{comparing && differs(k) && <small>Different</small>}</th>{comparing && <td>{display(primary.fields,k)}</td>}<td>{display(source.fields,k)}</td></tr>)}
        </tbody></table>
        {!shown.length && <p className="muted">{comparing && differences ? "No differing fields match this filter." : "No comparable fields recorded or matching this filter."}</p>}
      </>}
      {Object.keys(source.tags).length > 0 && <details><summary>All recorded source tags ({Object.keys(source.tags).length})</summary><table className="review-metadata-table"><tbody>{Object.keys(source.tags).sort().map(k => <tr key={k}><th scope="row">{k}</th><td>{display(source.tags,k)}</td></tr>)}</tbody></table></details>}
    </div>
  </section>;
}
