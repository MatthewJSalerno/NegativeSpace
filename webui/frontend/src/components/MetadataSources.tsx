import { useEffect, useId, useState } from "react";
import { api, type MetadataView, type MetadataSourceView } from "../api";
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
export function MetadataSources({ photoId, refreshKey, editable = false, jobRunning = false, onEdit }: { photoId: number; refreshKey: number; editable?: boolean; jobRunning?: boolean; onEdit?: (donor?: MetadataSourceView) => void }) {
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
  const sidecars = data.sources.filter(s => s.kind === "sidecar_xmp");
  const canCopyDate = source.id !== primary?.id && source.available && own(source.fields,"date_taken");
  const dateAlternatives = primary?.available && !own(primary.fields, "date_taken")
    ? data.sources.filter(s => s.id !== primary.id && s.available && typeof s.fields.date_taken === "string" && s.fields.date_taken !== "") : [];
  const comparing = compare && !!primary && source.id !== primary.id && primary.available && source.available;
  const fields = [...new Set(["date_taken", ...Object.keys(source.fields), ...(comparing ? Object.keys(primary.fields) : [])])].sort((a, b) => a === "date_taken" ? -1 : b === "date_taken" ? 1 : a.localeCompare(b));
  const differs = (key: string) => !!primary && (own(source.fields, key) !== own(primary.fields, key) || stable(comparable(source.fields[key], key)) !== stable(comparable(primary.fields[key], key)));
  const shown = fields.filter(k => (!comparing || !differences || differs(k)) && `${LABELS[k] ?? k} ${display(source.fields,k)} ${comparing ? display(primary.fields,k) : ""}`.toLowerCase().includes(query.toLowerCase()));
  const tags = [...new Set([...Object.keys(source.tags), ...(comparing ? Object.keys(primary.tags) : [])])].sort();
  const tagDiffers = (key: string) => !!primary && (own(source.tags, key) !== own(primary.tags, key) || stable(source.tags[key]) !== stable(primary.tags[key]));
  const shownTags = tags.filter(k => (!comparing || !differences || tagDiffers(k)) && `${k} ${display(source.tags,k)} ${comparing ? display(primary.tags,k) : ""}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="info-section metadata-sources">
    <h3>Metadata sources</h3>
    <p className="section-note">Viewing or comparing metadata does not change the photo or its primary source.</p>
    {data.notice && <p className="section-note">{data.notice}</p>}
    {data.issues.length > 0 && <div className="notice"><strong>Metadata needs attention</strong>
      <ul>{data.issues.map((issue, i) => <li key={i}>{issue.detail || issue.code.replaceAll("_", " ")}</li>)}</ul>
      <a href={logUrl({photo:photoId})} onClick={follow}>View photo logs</a>
    </div>}
    {!!data.warnings?.length && <section className="info-section" aria-label="Metadata notes">
      <h3>Metadata notes</h3>
      <p className="section-note">These notes alone do not prevent Copy or Move. Original metadata is preserved when transferring the file.</p>
      {data.warnings.map((note, i) => <div key={i}>
        <p>{note.reason}</p>
        {note.detail && <details><summary>Technical details</summary><p>{note.detail}</p></details>}
      </div>)}
    </section>}
    <TabList label="Metadata sources" idBase={id} value={kind} className="inspector-tabs" onChange={next => {
      const target = data.sources.find(s => s.kind === next && s.id === data.primary_id) ?? data.sources.find(s => s.kind === next)!;
      setSelected(target.id); setQuery("");
    }} tabs={kinds.map(k => ({ value:k, label:<>{k === "sidecar_xmp" ? "XMP Sidecar" : k === "embedded_xmp" ? "Embedded XMP" : "EXIF"}{primary?.kind === k && <> <span className="badge">Primary</span></>}</> }))} />
    <div role="tabpanel" {...tabPanel(id, kind, kind)}>
      {sidecars.length > 1 && <div className="metadata-version-slot" style={{ visibility: kind === "sidecar_xmp" ? undefined : "hidden" }} aria-hidden={kind !== "sidecar_xmp" || undefined}>
        <label>Sidecar version <select value={kind === "sidecar_xmp" ? source.id : sidecars[0].id} disabled={kind !== "sidecar_xmp"}
          onChange={e => setSelected(e.target.value)}>{sidecars.map((s, i) => <option key={s.id} value={s.id}>{s.version_id != null ? `Version ${s.version_id}` : `Unreadable sidecar ${i + 1}`}{s.id === data.primary_id ? " · Primary" : " · Alternative"}</option>)}</select></label>
      </div>}
      {source.issues.map((issue, i) => <p key={i} className="notice">{issue.detail || issue.code.replaceAll("_", " ")}</p>)}
      {!source.available ? <p className="muted">{source.issues.length ? "This metadata could not be read. See the issue above or open the photo logs." : "No metadata recorded for this source."}</p> : <>
        <div className="metadata-source-options">
          <label className="checkbox-row" style={{ visibility: primary?.available && primary.id !== source.id ? undefined : "hidden" }}><input type="checkbox" disabled={!primary?.available || primary.id === source.id} checked={compare} onChange={e => setCompare(e.target.checked)} />Compare with primary</label>
          <label className="checkbox-row" style={{ visibility: comparing ? undefined : "hidden" }}><input type="checkbox" disabled={!comparing} checked={differences} onChange={e => setDifferences(e.target.checked)} />Show differences only</label>
        </div>
        <SearchField placeholder="Filter fields" value={query} onValueChange={setQuery} aria-label="Filter source fields" clearLabel="Clear source field filter" />
        <p className="section-note">Dates are shown as recorded; no time zone is assumed.</p>
        <table className="review-metadata-table"><caption>{comparing ? `${source.label} compared with ${primary.label}` : source.label}</caption><thead><tr><th scope="col">Field</th>{comparing && <th scope="col">Primary value</th>}<th scope="col">{comparing ? "This source" : "Value"}</th></tr></thead><tbody>
          {shown.map(k => <tr key={k} data-different={comparing && differs(k)}><th scope="row">{LABELS[k] ?? k}{comparing && differs(k) && <small>Different</small>}</th>{comparing && <td>{display(primary.fields,k)}</td>}<td>{display(source.fields,k)}{k === "date_taken" && editable && onEdit && <>
            {source.id === primary?.id ? <>{" · "}<button className="link" disabled={jobRunning} title={jobRunning ? "Wait for the running job to finish." : "Edit Date taken in the primary metadata source."} onClick={() => onEdit()}>Edit metadata date…</button></>
              : canCopyDate && <>{" · "}<button className="link" disabled={jobRunning} title={jobRunning ? "Wait for the running job to finish." : "Copy only Date taken into the primary metadata source."} onClick={() => onEdit(source)}>Copy date to primary…</button></>}
          </>}
          {k === "date_taken" && source.id === primary?.id && dateAlternatives.length > 0 && <p className="section-note">Primary has no Date taken. A date is recorded in {dateAlternatives.map((alternative, i) => <span key={alternative.id}>{i > 0 && ", "}<button className="link" onClick={() => {setSelected(alternative.id); setQuery("");}}>{alternative.label}</button></span>)}. Review it before deciding whether to copy.</p>}
          </td></tr>)}
        </tbody></table>
        {!shown.length && <p className="muted">{comparing && differences ? "No differing fields match this filter." : "No comparable fields recorded or matching this filter."}</p>}
      </>}
      {tags.length > 0 && <details><summary>All recorded source tags ({shownTags.length}{shownTags.length !== tags.length ? ` of ${tags.length}` : ""})</summary>
        {comparing && <p className="section-note">These are the recorded tag names and values. EXIF and XMP may name or store the same detail differently. Use the common fields above to compare them.</p>}
        <table className="review-metadata-table"><caption>{comparing ? `Recorded tags: ${source.label} compared with ${primary.label}` : `Recorded tags: ${source.label}`}</caption>
          <thead><tr><th scope="col">Tag</th>{comparing && <th scope="col">Primary value</th>}<th scope="col">{comparing ? "This source" : "Value"}</th></tr></thead>
          <tbody>{shownTags.map(k => <tr key={k} data-different={comparing && tagDiffers(k)}><th scope="row">{k}{comparing && tagDiffers(k) && <small>Different</small>}</th>{comparing && <td>{display(primary.tags,k)}</td>}<td>{display(source.tags,k)}</td></tr>)}</tbody>
        </table>
        {!shownTags.length && <p className="muted">{comparing && differences ? "No differing tags match this filter." : "No recorded tags match this filter."}</p>}
      </details>}
    </div>
  </section>;
}
