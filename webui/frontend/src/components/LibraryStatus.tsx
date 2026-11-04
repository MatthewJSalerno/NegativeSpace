import { useEffect, useState } from "react";
import { api, type LibraryCheck, type LibraryStatus as Status } from "../api";
import { day } from "../format";
import { follow } from "../nav";
import { ACTIVE, CHECK_STARTED, checkResult, stoppedReason } from "../libraryCheck";
import { CheckLibraryDialog } from "./CheckLibraryDialog";

// How often the status follows a running check.
const POLL_MS = 2000;

// The colour of a result's words and its row's left edge (ui-design "Page frame").
function tone(check: LibraryCheck): string {
  return check.tone === "bad" ? "status-bad" : check.tone === "warn" ? "status-warn" : "";
}

// The library status at the foot of the sidebar (webui-spec 7.6, ui-design "Page frame"),
// under its own heading like Activity: when the source was last indexed and the library
// last checked. Each row opens its job's log; never checked, the Library row opens the
// Check library dialog, never a job.
export function LibraryStatus({ refresh, onNavigate }: { refresh?: unknown; onNavigate?: () => void }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [asking, setAsking] = useState(false);
  const [started, setStarted] = useState(0);
  useEffect(() => {
    const bump = () => setStarted(n => n + 1);
    window.addEventListener(CHECK_STARTED, bump);
    return () => window.removeEventListener(CHECK_STARTED, bump);
  }, []);
  const running = !!status?.latest && ACTIVE.includes(status.latest.status);
  useEffect(() => {
    let live = true;
    const load = () => api.libraryStatus().then(s => live && setStatus(s), () => live && setStatus(null));
    void load();
    const timer = running ? window.setInterval(load, POLL_MS) : undefined;
    return () => { live = false; window.clearInterval(timer); };
  }, [refresh, started, running]);
  if (!status) return null;
  const go: React.MouseEventHandler<HTMLAnchorElement> = e => { onNavigate?.(); follow(e); };
  const { source, latest, result } = status;
  const stopped = latest && !running && latest.run_id !== result?.run_id && latest.status === "Failed" ? latest : null;
  const progress = running && latest?.progress?.total ? ` ${Math.floor(100 * latest.progress.done / latest.progress.total)}%` : "";
  return <section className="library-status" aria-labelledby="library-status-heading">
    <h2 className="sidebar-heading" id="library-status-heading">Status</h2>
    {source
      ? <a className="status-row" href={`/logs?run=${source.run_id}`} onClick={go}>
          <span>Source</span><span className="status-detail">indexed {day(source.at)}</span></a>
      : <div className="status-row"><span>Source</span><span className="status-detail">not indexed yet</span></div>}
    {running && latest && <a className="status-row status-accent" href={`/logs?run=${latest.run_id}`} onClick={go} role="status">
      <span>Library</span><span className="status-detail">checking…{progress}</span></a>}
    {stopped && <a className="status-row status-warn" href={`/logs?run=${stopped.run_id}`} onClick={go}>
      <span>Library</span><span className="status-detail">check on {day(stopped.started_at)} couldn't run</span>
      <span className="status-result">{stoppedReason(stopped)}</span></a>}
    {!running && (result
      ? <a className={`status-row ${stopped ? "" : tone(result)}`} href={`/logs?run=${result.run_id}`} onClick={go}>
          <span>Library{stopped ? ", last result" : ""}</span><span className="status-detail">checked {day(result.ended_at ?? result.started_at)}</span>
          <span className="status-result">{checkResult(result)}</span></a>
      : !stopped && <button type="button" className="status-row" onClick={() => setAsking(true)}>
          <span>Library</span><span className="status-detail">not checked yet</span>
          <span className="status-action">Check library…</span></button>)}
    {asking && <CheckLibraryDialog onClose={() => setAsking(false)} />}
  </section>;
}
