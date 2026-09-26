import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Logo } from "./Logo";
import { VersionTag } from "./VersionTag";
import { api, ApiError, type LogFilters, type Operation, type OperationPage, type Run, type Status } from "../api";
import { count, instant, plural } from "../format";
import { modeName, summary, useDismissedRun, useJobFeed } from "../jobs";
import { follow, useHeaderHeight } from "../nav";
import { usePaged } from "../paged";
import { ActionsMenu } from "./ActionsMenu";
import { ConfirmDialog, transferConfirm, type Confirm } from "./Confirm";
import { FinishedBanner, JobDrawer } from "./JobDrawer";

// Entries loaded at a time as a job's list scrolls on.
const LOG_BATCH = 100;
// Jobs listed in the log, newest first; the API's own cap.
const RUNS_LISTED = 500;

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
  if (op.run_level) return "A folder or the whole job, not one photo: nothing inside it was examined. Fix the folder's access, then run an Index.";
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

// A hint that calls for an Index offers it, rather than sending the user to find it.
const CALLS_FOR_INDEX = /run an index/i;

function readFilters(): LogFilters {
  const p = new URLSearchParams(window.location.search);
  return {
    run: p.getAll("run").map(Number).filter((n) => n > 0),
    status: p.getAll("status"),
    photo: p.get("photo") ? Number(p.get("photo")) : null,
    q: p.get("q") ?? "",
    since: p.get("since") ?? "",
    until: p.get("until") ?? "",
  };
}

// A local calendar date as the UTC instant its day starts, for the API's filter.
function dayStart(date: string, plusDays = 0): string {
  if (!date) return "";
  const [y, m, d] = date.split("-").map(Number);
  return new Date(y, m - 1, d + plusDays).toISOString();
}

// A job the catalog has recorded; only those have entries to list.
type RecordedRun = Run & { id: number };

function retryModeOf(run: Run): "index" | "copy" | "move" | null {
  return run.mode === "INDEX" ? "index" : run.mode === "COPY" ? "copy" : run.mode === "MOVE" ? "move" : null;
}

// The operations log and, filtered to failures, the Error Center (webui-spec 5.3,
// 5.4), grouped by job: each job is one line until opened. Filters are in the
// address bar, so a banner link, the Inspector's History button or a bookmark opens
// exactly this view; a link to one job opens with that job expanded.
export function LogsPage({ status, refreshStatus, onOpenSettings }: {
  status: Status;
  refreshStatus: () => void;
  onOpenSettings: () => void;
}) {
  const initial = useMemo(readFilters, []);
  const [filters, setFilters] = useState<LogFilters>(initial);
  const [dates, setDates] = useState(() => {
    const p = new URLSearchParams(window.location.search);
    return { from: p.get("from") ?? "", to: p.get("to") ?? "" };
  });
  const [search, setSearch] = useState(initial.q);
  const [totals, setTotals] = useState<OperationPage | null>(null);
  const [runs, setRuns] = useState<RecordedRun[] | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set(initial.run.length === 1 ? initial.run : []));
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [dismissedId, dismissRun] = useDismissedRun();
  const { jobs, connection } = useJobFeed();
  const jobRunning = jobs.active != null && jobs.active.presented_status !== "Interrupted";
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const header = useRef<HTMLElement>(null);
  useHeaderHeight(header);

  const apiFilters = { ...filters, since: dayStart(dates.from), until: dayStart(dates.to, 1) };

  useEffect(() => {
    const t = window.setTimeout(() => {
      if (search.trim() !== filters.q) setFilters((f) => ({ ...f, q: search.trim() }));
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
    window.history.replaceState(null, "", `/logs${p.size ? `?${p}` : ""}`);
  }, [filters, dates]);

  // The counts only: which jobs match, and how many entries each and each status holds.
  useEffect(() => {
    let live = true;
    api.operations(apiFilters, 1, 1).then(
      (d) => { if (live) { setTotals(d); setError(null); } },
      (e) => live && setError(e instanceof ApiError ? e.message : "The log could not be loaded."),
    );
    return () => { live = false; };
  }, [filters, dates, refreshKey]);

  useEffect(() => {
    api.runs(RUNS_LISTED).then((r) => setRuns(r.runs.filter((run): run is RecordedRun => run.id != null)), () => setRuns([]));
  }, [refreshKey]);

  // A job finishing changes the log.
  const lastKey = jobs.last && !jobRunning ? `${jobs.last.id}:${jobs.last.status}` : null;
  useEffect(() => { if (lastKey) { setRefreshKey((k) => k + 1); refreshStatus(); } }, [lastKey]);

  // The Actions menu, as in the Library: whole-library actions start here too.
  const startJob = (mode: "index" | "copy" | "move") => async () => {
    setNotice(null);
    try {
      await api.startJob({ mode });
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : "The job could not be started.");
    }
  };

  const set = (patch: Partial<LogFilters>) => setFilters((f) => ({ ...f, ...patch }));
  const toggleStatus = (s: string) =>
    set({ status: filters.status.includes(s) ? filters.status.filter((x) => x !== s) : [...filters.status, s] });
  const toggleRun = (id: number) => setExpanded((cur) => {
    const next = new Set(cur);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  // Retrying is a new job over the photos behind one job's failures, taken from the
  // failed operations themselves (webui-spec 5.3). There is no separate retry.
  const retry = async (run: RecordedRun) => {
    const mode = retryModeOf(run);
    if (!mode) return;
    setNotice(null);
    try {
      const ids = await api.retryIds({ ...apiFilters, run: [run.id], status: ["Failed"] });
      if (ids.more_than_limit) {
        setNotice(`More than ${count(ids.limit)} photos failed. Retry them in smaller groups, or run the ${modeName(run.mode)} again for everything.`);
        return;
      }
      if (ids.photo_ids.length === 0) {
        setNotice("None of these failures belongs to a photo, so there is nothing to retry. Fix the folder's access, then run an Index.");
        return;
      }
      await api.startJob({ mode, file_ids: ids.photo_ids });
      setNotice(`Retrying ${plural(ids.photo_ids.length, "photo")} as a new ${modeName(run.mode)}. A retry does not by itself fix an unreadable file or a content mismatch.`);
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : "The retry could not be started.");
    }
  };

  const runIndex = async () => {
    setNotice(null);
    try {
      await api.startJob({ mode: "index" });
      setNotice("Index started. Its progress shows at the top of the page.");
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : "The Index could not be started.");
    }
  };
  const indexButton = (
    <button className="link" onClick={runIndex} disabled={jobRunning} title={jobRunning ? "A job is running." : undefined}>
      Run an Index
    </button>
  );

  const failuresOnly = filters.status.length === 1 && filters.status[0] === "Failed";
  // With any filter other than the job, a job with nothing matching is left out;
  // without one, every job is listed, including one that recorded nothing.
  const narrowed = filters.status.length > 0 || filters.photo != null || !!filters.q || !!dates.from || !!dates.to;
  const groups = (runs ?? []).filter((r) =>
    (filters.run.length === 0 || filters.run.includes(r.id)) && (!narrowed || (totals?.run_counts[String(r.id)] ?? 0) > 0));
  const statuses = Object.keys(STATUS_LABEL).filter((s) => (totals?.status_counts[s] ?? 0) > 0 || filters.status.includes(s));
  const allOpen = groups.length > 0 && groups.every((r) => expanded.has(r.id));
  // What narrows the log, named in one line with one reset.
  const active = [
    ...filters.run.map((r) => `job #${r}`),
    ...filters.status.map((st) => STATUS_LABEL[st] ?? st),
    ...(filters.photo != null ? [`photo #${filters.photo}`] : []),
    ...(filters.q ? [`“${filters.q}”`] : []),
    ...(dates.from ? [`from ${dates.from}`] : []),
    ...(dates.to ? [`to ${dates.to}`] : []),
  ];
  const clearAll = () => {
    setFilters({ run: [], status: [], photo: null, q: "", since: "", until: "" });
    setSearch("");
    setDates({ from: "", to: "" });
  };

  return (
    <div className="app">
      <header className="toolbar" ref={header}>
        <div className="toolbar-row">
          <h1 className="brand"><Logo />NegativeSpace</h1>
          <nav className="pages" aria-label="Pages">
            <a className="button-link" href="/" onClick={follow}>Library</a>
            <ActionsMenu
              state={{ jobRunning, noPhotos: status.photos === 0, selected: 0, tooMany: false, maxSelection: 1000,
                       eligible: status.eligible, copied: status.copied }}
              onIndex={startJob("index")}
              onTransfer={(mode) => setConfirm(transferConfirm(mode, status, undefined, startJob(mode)))} />
            <a className="button-link active" href="/logs" onClick={follow} aria-current="page">Logs</a>
          </nav>
          <div className="toolbar-actions">
            <VersionTag version={status.version} />
            <button className="icon" onClick={onOpenSettings} aria-label="Settings" title="Settings">⚙</button>
          </div>
        </div>
        <JobDrawer jobs={jobs} connection={connection} />
        <FinishedBanner jobs={jobs} dismissedId={dismissedId} onDismiss={dismissRun} />
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
          <input type="search" placeholder="Search paths and messages" value={search}
                 onChange={(e) => setSearch(e.target.value)} aria-label="Search the log" />
          <label className="field-inline"><span>From</span>
            <input type="date" value={dates.from} onChange={(e) => setDates((d) => ({ ...d, from: e.target.value }))} aria-label="From date" />
          </label>
          <label className="field-inline"><span>To</span>
            <input type="date" value={dates.to} onChange={(e) => setDates((d) => ({ ...d, to: e.target.value }))} aria-label="To date" />
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
              <span>{STATUS_LABEL[s]}</span> <span className="view-count">({count(totals?.status_counts[s] ?? 0)})</span>
            </button>
          ))}
        </div>

        {notice && <p className="notice" role="status">{notice}{CALLS_FOR_INDEX.test(notice) && <> {indexButton}</>}</p>}
        {error && <p className="error">{error}</p>}

        {active.length > 0 && (
          <p className="dates-filter-line">
            Showing: {active.join(" · ")} · <button className="link" onClick={clearAll}>Clear all filters</button>
          </p>
        )}
        {runs && totals && (
          <div className="job-list-head">
            <span className="muted">
              {plural(totals.total, "entry", "entries")} in {plural(groups.length, "job")}
              {filters.run.length > 0 && <> · <button className="link" onClick={() => set({ run: [] })}>Show all jobs</button></>}
            </span>
            {groups.length > 1 && (
              <button className="link" onClick={() => setExpanded(allOpen ? new Set() : new Set(groups.map((r) => r.id)))}>
                {allOpen ? "Collapse all" : "Expand all"}
              </button>
            )}
          </div>
        )}
        {runs && totals && groups.length === 0 && <p className="empty">Nothing recorded matches these filters.</p>}

        <ol className="job-list">
          {groups.map((run) => {
            const open = expanded.has(run.id);
            const matches = totals?.run_counts[String(run.id)] ?? 0;
            const s = run.outcome ? summary(run) : null;
            return (
              <li key={run.id} className={`job-group job-${s?.tone ?? "neutral"} ${open ? "open" : ""}`}>
                <button className="job-head" aria-expanded={open} onClick={() => toggleRun(run.id)}>
                  <span className="job-caret" aria-hidden="true">{open ? "▾" : "▸"}</span>
                  <span className="job-title">
                    <strong>#{run.id} {s?.headline ?? modeName(run.mode)}</strong>
                    <span className="muted">{instant(run.started_at)}</span>
                  </span>
                  <span className="job-detail">{s?.detail}</span>
                  <span className="job-count">{plural(matches, "entry", "entries")}</span>
                </button>
                {open && (
                  <JobEntries run={run} filters={apiFilters} refreshKey={refreshKey} activePhoto={filters.photo} indexButton={indexButton}
                              onPhoto={(id) => set({ photo: id })} onRetry={() => retry(run)} jobRunning={jobRunning} />
                )}
              </li>
            );
          })}
        </ol>
        <p className="muted back"><a href="/" onClick={follow}>← Back to the library</a></p>
      </main>
      {confirm && <ConfirmDialog confirm={confirm} onClose={() => setConfirm(null)} />}
    </div>
  );
}

// One job's entries under the page's filters, loading more as the list scrolls on.
// The job's header line sticks to the top meanwhile, so collapsing it is always at hand.
function JobEntries({ run, filters, refreshKey, activePhoto, indexButton, onPhoto, onRetry, jobRunning }: {
  run: RecordedRun;
  indexButton: ReactNode;
  filters: LogFilters;
  refreshKey: number;
  activePhoto: number | null;
  onPhoto: (id: number) => void;
  onRetry: () => void;
  jobRunning: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  const scoped = { ...filters, run: [run.id] };
  const list = usePaged<OperationPage, Operation>((p) => api.operations(scoped, p, LOG_BATCH), JSON.stringify(scoped),
                                                   { page: 1, n: 0 }, LOG_BATCH, refreshKey, setError);
  const more = useRef<HTMLDivElement>(null);
  const items = useMemo(() => [...list.pages.keys()].sort((x, y) => x - y).flatMap((p) => list.pages.get(p) ?? []), [list.pages]);
  const data = list.meta;
  const hasMore = !!data && items.length < data.total;
  useEffect(() => {
    if (!more.current) return;
    const observer = new IntersectionObserver(([e]) => e.isIntersecting && list.load(list.last + 1), { rootMargin: "600px 0px" });
    observer.observe(more.current);
    return () => observer.disconnect();
  }, [list.last, list.load, hasMore]);

  if (error) return <p className="error job-body">{error}</p>;
  if (!data) return <p className="muted job-body">Loading…</p>;
  const failed = data.status_counts.Failed ?? 0;
  const canRetry = failed > 0 && retryModeOf(run) != null;

  return (
    <div className="job-body">
      {canRetry && (
        <div className="retry">
          <button onClick={onRetry} disabled={jobRunning} title={jobRunning ? "A job is running." : undefined}>
            Retry the {plural(failed, "failed photo")} ({modeName(run.mode)})
          </button>
        </div>
      )}
      {data.total === 0 ? <p className="empty">This job recorded nothing{filters.status.length || filters.q ? " that matches these filters" : ""}.</p> : (
        <>
          <table className="log-table log-entries">
            <colgroup><col className="col-time" /><col className="col-status" /><col className="col-file" /><col /></colgroup>
            <thead>
              <tr><th>Time</th><th>Status</th><th>File</th><th>Details</th></tr>
            </thead>
            <tbody>
              {items.map((op) => {
                const hint = failureHint(op);
                return (
                  <tr key={op.id} className={`log-${op.status.toLowerCase()}`}>
                    <td className="nowrap">{instant(op.timestamp)}</td>
                    <td className="log-status">
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
                          {activePhoto !== op.photo_id && (
                            <button className="link" onClick={() => onPhoto(op.photo_id as number)}>its history</button>
                          )}
                        </div>
                      )}
                    </td>
                    <td>
                      {op.error_message && <div className="message">{op.error_message}</div>}
                      {hint && <div className="hint">{hint}{CALLS_FOR_INDEX.test(hint) && <> {indexButton}</>}</div>}
                      {op.status === "Failed" && op.photo_status && op.photo_status !== "Failed" && (
                        <div className="muted">The photo is now {STATUS_LABEL[op.photo_status]?.toLowerCase() ?? op.photo_status}.</div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {hasMore
            ? <div ref={more} className="page-sentinel muted">Loading more entries… ({count(items.length)} of {count(data.total)})</div>
            : data.total > LOG_BATCH && <p className="muted">All {count(data.total)} entries shown.</p>}
        </>
      )}
    </div>
  );
}
