import { useEffect, useMemo, useState } from "react";
import { api, ApiError, type LogFilters, type Operation, type OperationPage, type Run } from "../api";
import { count, instant, plural } from "../format";
import { modeName, useJobFeed } from "../jobs";
import { follow } from "../nav";
import { FinishedBanner, JobDrawer } from "./JobDrawer";
import { Pager } from "./Pager";

const LOG_SIZES = [100, 250, 500];

// How the log names each recorded status. A scan records Pending for a file it
// catalogued and Duplicate for an exact copy.
const STATUS_LABEL: Record<string, string> = {
  Pending: "Indexed", Duplicate: "Indexed (duplicate)", Processing: "Unfinished", Completed: "Moved",
  Copied: "Copied", Failed: "Failed", Removed_Duplicate: "Duplicate removed",
  Found_At_Destination: "Found at destination", Skipped: "Skipped", Cancelled: "Cancelled", Renamed: "Renamed",
};

// What to do about a failure, from the recorded reason (webui-spec 5.3): a content
// mismatch reads differently from an unreadable file, and a changed source asks for
// an Index, not a permissions check.
function failureHint(op: Operation): string | null {
  if (op.status !== "Failed") return null;
  const m = op.error_message ?? "";
  if (op.run_level) return "A folder or the whole job, not one photo: nothing inside it was examined. Fix the folder's access, then index again.";
  if (m.startsWith("Duplicate verification failed") && m.includes("ChecksumMismatch"))
    return "The two copies' contents differ, so the source was kept. Nothing was deleted.";
  if (m.startsWith("Duplicate verification failed"))
    return "One of the files could not be read, so they were never compared. The source was kept.";
  if (m.startsWith("Source file changed")) return "The file moved or changed since the last Index. Run an Index, then try again.";
  if (/Permission denied|PermissionError/.test(m)) return "The container's user could not read or write this file. Check its permissions (PUID/PGID).";
  if (/Insufficient space/.test(m)) return "Free up space at the destination, then try again.";
  if (/differs from the catalog/.test(m)) return "The destination file is not what the catalog recorded. See the destination check.";
  return null;
}

function readFilters(): { filters: LogFilters; page: number } {
  const p = new URLSearchParams(window.location.search);
  return {
    filters: {
      run: p.getAll("run").map(Number).filter((n) => n > 0),
      status: p.getAll("status"),
      photo: p.get("photo") ? Number(p.get("photo")) : null,
      q: p.get("q") ?? "",
      since: p.get("since") ?? "",
      until: p.get("until") ?? "",
    },
    page: Math.max(1, Number(p.get("page")) || 1),
  };
}

// A local calendar date as the UTC instant its day starts, for the API's filter.
function dayStart(date: string, plusDays = 0): string {
  if (!date) return "";
  const [y, m, d] = date.split("-").map(Number);
  return new Date(y, m - 1, d + plusDays).toISOString();
}

// The operations log and, filtered to failures, the Error Center (webui-spec 5.3,
// 5.4). Everything is in the address bar, so a banner link, the Inspector's History
// button or a bookmark opens exactly this view.
export function LogsPage({ onOpenSettings }: { onOpenSettings: () => void }) {
  const initial = useMemo(readFilters, []);
  const [filters, setFilters] = useState<LogFilters>(initial.filters);
  const [dates, setDates] = useState(() => {
    const p = new URLSearchParams(window.location.search);
    return { from: p.get("from") ?? "", to: p.get("to") ?? "" };
  });
  const [search, setSearch] = useState(initial.filters.q);
  const [page, setPage] = useState(initial.page);
  const [pageSize, setPageSize] = useState(LOG_SIZES[0]);
  const [data, setData] = useState<OperationPage | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [dismissedId, setDismissedId] = useState<number | null>(null);
  const { jobs, connection } = useJobFeed();
  const jobRunning = jobs.active != null && jobs.active.presented_status !== "Interrupted";

  const apiFilters = { ...filters, since: dayStart(dates.from), until: dayStart(dates.to, 1) };

  useEffect(() => {
    const t = window.setTimeout(() => {
      if (search.trim() !== filters.q) { setFilters((f) => ({ ...f, q: search.trim() })); setPage(1); }
    }, 300);
    return () => window.clearTimeout(t);
  }, [search, filters.q]);

  useEffect(() => {
    const p = new URLSearchParams();
    filters.run.forEach((r) => p.append("run", String(r)));
    filters.status.forEach((s) => p.append("status", s));
    if (filters.photo != null) p.set("photo", String(filters.photo));
    if (filters.q) p.set("q", filters.q);
    if (dates.from) p.set("from", dates.from);
    if (dates.to) p.set("to", dates.to);
    if (page > 1) p.set("page", String(page));
    window.history.replaceState(null, "", `/logs${p.size ? `?${p}` : ""}`);
  }, [filters, dates, page]);

  useEffect(() => {
    let live = true;
    api.operations(apiFilters, page, pageSize).then(
      (d) => { if (live) { setData(d); setError(null); } },
      (e) => live && setError(e instanceof ApiError ? e.message : "The log could not be loaded."),
    );
    return () => { live = false; };
  }, [filters, dates, page, pageSize, refreshKey]);

  useEffect(() => {
    api.runs().then((r) => setRuns(r.runs), () => setRuns([]));
  }, [refreshKey]);

  // A job finishing changes the log.
  const lastKey = jobs.last && !jobRunning ? `${jobs.last.id}:${jobs.last.status}` : null;
  useEffect(() => { if (lastKey) setRefreshKey((k) => k + 1); }, [lastKey]);

  const set = (patch: Partial<LogFilters>) => { setFilters((f) => ({ ...f, ...patch })); setPage(1); };
  const toggleStatus = (s: string) =>
    set({ status: filters.status.includes(s) ? filters.status.filter((x) => x !== s) : [...filters.status, s] });

  const failuresOnly = filters.status.length === 1 && filters.status[0] === "Failed";
  const oneRun = filters.run.length === 1 ? runs.find((r) => r.id === filters.run[0]) : undefined;
  const retryMode = oneRun?.mode === "INDEX" ? "index" : oneRun?.mode === "COPY" ? "copy" : oneRun?.mode === "MOVE" ? "move" : null;

  // Retrying is a new job over the photos behind these failures, taken from the
  // failed operations themselves (webui-spec 5.3). There is no separate retry.
  const retry = async () => {
    if (!retryMode || !oneRun) return;
    setNotice(null);
    try {
      const ids = await api.retryIds(apiFilters);
      if (ids.more_than_limit) {
        setNotice(`More than ${count(ids.limit)} photos failed. Retry them in smaller groups, or run the ${modeName(oneRun.mode)} again for everything.`);
        return;
      }
      if (ids.photo_ids.length === 0) {
        setNotice("None of these failures belongs to a photo, so there is nothing to retry. Fix the folder, then index again.");
        return;
      }
      await api.startJob({ mode: retryMode, file_ids: ids.photo_ids });
      setNotice(`Retrying ${plural(ids.photo_ids.length, "photo")} as a new ${modeName(oneRun.mode)}. A retry does not by itself fix an unreadable file or a content mismatch.`);
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : "The retry could not be started.");
    }
  };

  const pages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;
  const statuses = Object.keys(STATUS_LABEL).filter((s) => (data?.status_counts[s] ?? 0) > 0 || filters.status.includes(s));

  return (
    <div className="app">
      <header className="toolbar">
        <div className="toolbar-row">
          <h1 className="brand">NegativeSpace</h1>
          <nav className="pages" aria-label="Pages">
            <a className="button-link" href="/" onClick={follow}>Library</a>
            <a className="button-link active" href="/logs" onClick={follow} aria-current="page">Logs</a>
          </nav>
          <div className="toolbar-actions">
            <button className="icon" onClick={onOpenSettings} aria-label="Settings" title="Settings">⚙</button>
          </div>
        </div>
        <JobDrawer jobs={jobs} connection={connection} />
        <FinishedBanner jobs={jobs} dismissedId={dismissedId} onDismiss={setDismissedId} />
      </header>

      <main className="logs">
        <h2>{failuresOnly ? "Failures" : "Log"}{filters.photo != null ? ` for photo #${filters.photo}` : ""}</h2>
        {failuresOnly && (
          <p className="muted">
            Every attempt that failed, whatever the photo's status is now. A failure with no photo is about a folder
            or the whole job. Retrying runs the same job again for the photos behind these failures.
          </p>
        )}
        {filters.photo != null && (
          <p className="muted">
            Everything recorded for this photo across jobs, including its copies and moves.{" "}
            <a href={`/?photo=${filters.photo}`} onClick={follow}>Open the photo</a>
            {" · "}<a href="/logs" onClick={follow}>Show all</a>
          </p>
        )}

        <div className="log-filters">
          <label className="field-inline">
            <span>Job</span>
            <select value={filters.run.length === 1 ? String(filters.run[0]) : filters.run.length ? "several" : ""}
                    onChange={(e) => set({ run: e.target.value && e.target.value !== "several" ? [Number(e.target.value)] : [] })}
                    aria-label="Job">
              <option value="">All jobs</option>
              {filters.run.length > 1 && <option value="several">{count(filters.run.length)} jobs</option>}
              {runs.map((r) => (
                <option key={r.id} value={String(r.id)}>
                  #{r.id} {modeName(r.mode)} · {instant(r.started_at)} · {r.outcome?.verdict.replace("_", " ")}
                </option>
              ))}
            </select>
          </label>
          <input type="search" placeholder="Search paths and messages" value={search}
                 onChange={(e) => setSearch(e.target.value)} aria-label="Search the log" />
          <label className="field-inline"><span>From</span>
            <input type="date" value={dates.from} onChange={(e) => { setDates((d) => ({ ...d, from: e.target.value })); setPage(1); }} aria-label="From date" />
          </label>
          <label className="field-inline"><span>To</span>
            <input type="date" value={dates.to} onChange={(e) => { setDates((d) => ({ ...d, to: e.target.value })); setPage(1); }} aria-label="To date" />
          </label>
          <span className="export">
            Export: <a href={api.exportUrl(apiFilters, "csv")} download>CSV</a> · <a href={api.exportUrl(apiFilters, "json")} download>JSON</a>
          </span>
        </div>

        <div className="status-chips" role="group" aria-label="Statuses">
          <button className={filters.status.length === 0 ? "active" : ""} onClick={() => set({ status: [] })}>All statuses</button>
          {statuses.map((s) => (
            <button key={s} className={`${filters.status.includes(s) ? "active" : ""} ${s === "Failed" ? "chip-failed" : ""}`}
                    aria-pressed={filters.status.includes(s)} onClick={() => toggleStatus(s)}>
              {STATUS_LABEL[s]} ({count(data?.status_counts[s] ?? 0)})
            </button>
          ))}
        </div>

        {failuresOnly && oneRun && retryMode && data && data.total > 0 && (
          <div className="retry">
            <button onClick={retry} disabled={jobRunning}
                    title={jobRunning ? "A job is running." : undefined}>Retry these photos ({modeName(oneRun.mode)})</button>
          </div>
        )}
        {notice && <p className="notice" role="status">{notice}</p>}
        {error && <p className="error">{error}</p>}

        {data && data.total === 0 && <p className="empty">Nothing recorded matches these filters.</p>}
        {data && data.total > 0 && (
          <>
            <Pager page={page} pages={pages} total={data.total} pageSize={pageSize} onPage={setPage}
                   onPageSize={(n) => { setPageSize(n); setPage(1); }} sizes={LOG_SIZES} noun="entry" nouns="entries" />
            <table className="log-table">
              <thead>
                <tr><th>Time</th><th>Job</th><th>Status</th><th>File</th><th>Details</th></tr>
              </thead>
              <tbody>
                {data.items.map((op) => {
                  const hint = failureHint(op);
                  return (
                    <tr key={op.id} className={`log-${op.status.toLowerCase()}`}>
                      <td className="nowrap">{instant(op.timestamp)}</td>
                      <td className="nowrap">
                        <button className="link" onClick={() => set({ run: [op.run_id] })} title="Show only this job">
                          #{op.run_id} {modeName(op.mode)}
                        </button>
                      </td>
                      <td>
                        {STATUS_LABEL[op.status] ?? op.status}
                        {op.recovery && <div><span className="badge">Recovery of earlier work</span></div>}
                        {op.run_level && op.status === "Failed" && <div><span className="badge">Folder or job</span></div>}
                      </td>
                      <td>
                        {op.source_path && <div><code>{op.source_path}</code></div>}
                        {op.dest_path && <div className="muted">→ <code>{op.dest_path}</code></div>}
                        {op.photo_id != null && (
                          <div className="row-links">
                            <a href={`/?photo=${op.photo_id}`} onClick={follow}>Photo #{op.photo_id}</a>
                            {filters.photo !== op.photo_id && (
                              <button className="link" onClick={() => set({ photo: op.photo_id })}>its history</button>
                            )}
                          </div>
                        )}
                      </td>
                      <td>
                        {op.error_message && <div className="message">{op.error_message}</div>}
                        {hint && <div className="hint">{hint}</div>}
                        {op.status === "Failed" && op.photo_status && op.photo_status !== "Failed" && (
                          <div className="muted">The photo is now {STATUS_LABEL[op.photo_status]?.toLowerCase() ?? op.photo_status}.</div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <Pager page={page} pages={pages} total={data.total} pageSize={pageSize} onPage={setPage}
                   onPageSize={(n) => { setPageSize(n); setPage(1); }} sizes={LOG_SIZES} noun="entry" nouns="entries" />
          </>
        )}
        <p className="muted back"><a href="/" onClick={follow}>← Back to the library</a></p>
      </main>
    </div>
  );
}
