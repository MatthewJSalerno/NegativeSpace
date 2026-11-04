import { useEffect, useState } from "react";
import { api, type LibraryCheck, type LibraryFinding } from "../api";
import { count, plural } from "../format";
import { photoUrl, follow } from "../nav";
import { FINDING_LABEL, HOUSEKEEPING_LABEL, checkResult, depthName, noticeClass, stoppedReason } from "../libraryCheck";
import { Pager } from "./Pager";

const PAGE = 100;

// A library check's entry in Logs (webui-spec 7.6): every finding, most serious first,
// with what it means and what can be done now, whole folders as one finding each, and
// what is only counted. Its own export carries every finding.
export function LibraryCheckFindings({ runId, refreshKey }: { runId: number; refreshKey: number }) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<(LibraryCheck & { total: number; findings: LibraryFinding[] }) | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.libraryFindings(runId, page, PAGE).then(d => live && setData(d), e => live && setError(e.message));
    return () => { live = false; };
  }, [runId, page, refreshKey]);
  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  if (data.stopped) return <p className="notice notice-warn"><strong>Couldn't run.</strong> {stoppedReason(data)} Nothing was checked and nothing was recorded.</p>;
  // Whole folders, other types and a moved photo's new file are said once, elsewhere.
  const rows = data.findings.filter(f => !f.folder && !["other_type", "unrecognised", "moved_here"].includes(f.finding));
  const housekeeping = Object.entries(data.housekeeping);
  const others = Object.entries(data.other_types);
  return <section className="library-findings" aria-label="Library check findings">
    <p>{depthName(data.depth)} check · {plural(data.intact, "photo")} as recorded · <span className={data.tone === "bad" ? "error" : data.tone === "warn" ? "warning-text" : undefined}>{checkResult(data)}</span></p>
    {data.total > 0 && <div className="page-actions" role="group" aria-label="Export findings">
      <span className="muted">Export findings</span>
      <a href={api.libraryExportUrl(runId, "csv")} download>CSV</a>
      <a href={api.libraryExportUrl(runId, "json")} download>JSON</a>
    </div>}
    {data.renamed.length > 0 && <div className="library-renames">
      <p>{plural(data.renamed.length, "rename")} you made recorded, each matched by its checksum. The new names are kept.</p>
      <ul>{data.renamed.map(r => <li key={r.photo_id}><span className="path">{r.old}</span> → <span className="path">{r.new}</span>{" "}
        <a href={photoUrl(r.photo_id)} onClick={follow}>Photo #{r.photo_id}</a></li>)}</ul>
    </div>}
    {data.folders.map(g => <p key={g.folder} className={noticeClass(g.tone)}>
      {g.moved_to
        ? <>The folder <strong>{g.folder}</strong> was moved or renamed to <strong>{g.moved_to}</strong>: {plural(g.photos, "photo")}. Move it back, then check the library again.</>
        : <>The folder <strong>{g.folder}</strong> is missing: {plural(g.photos, "photo")}{g.lost ? `, ${count(g.lost)} with no copy anywhere` : ""}. Put it back, or restore it from a backup, then check the library again.</>}
    </p>)}
    {rows.length > 0 && <table className="log-table library-findings-table">
      <colgroup><col className="col-status" /><col className="col-file" /><col /></colgroup>
      <thead><tr><th>Found</th><th>File</th><th>What it means</th></tr></thead>
      <tbody>{rows.map(f => <tr key={f.path}>
        <td className={f.tone === "bad" ? "error" : f.tone === "warn" ? "warning-text" : "muted"}><strong>{FINDING_LABEL[f.finding] ?? f.finding}</strong></td>
        <td><span className="path">{f.relative}</span>
          {f.photo_id != null && <div className="row-links"><a href={photoUrl(f.photo_id)} onClick={follow}>Photo #{f.photo_id}</a></div>}</td>
        <td>{f.what}{f.todo && <div className="hint">{f.todo}</div>}</td>
      </tr>)}</tbody>
    </table>}
    {data.total > PAGE && <Pager page={page} pages={Math.ceil(data.total / PAGE)} total={data.total} pageSize={PAGE} sizes={[PAGE]}
      onPage={setPage} onPageSize={() => {}} />}
    {others.length > 0 && <p className="section-note">Other types, left untouched: {others.map(([ext, n]) => ext === "(none)" ? `${plural(n, "file")} with no extension` : `${plural(n, `${ext} file`)}`).join(" · ")}.
      {" "}<button className="link" onClick={() => window.dispatchEvent(new Event("ns-review-settings"))}>Change in Settings → Files</button></p>}
    {(housekeeping.length > 0 || data.sidecars > 0) && <p className="section-note">
      {housekeeping.length > 0 && <>{plural(housekeeping.reduce((n, [, k]) => n + k, 0), "file")} from other programs: {housekeeping.map(([k]) => HOUSEKEEPING_LABEL[k] ?? k).join(", ")}. </>}
      {data.sidecars > 0 && <>{plural(data.sidecars, "sidecar")} beside photos. </>}
      Left untouched and never warned about.</p>}
    {data.total === 0 && data.folders.length === 0 && data.renamed.length === 0 && <p className="muted">Every photo is where NegativeSpace filed it, as recorded.</p>}
  </section>;
}
