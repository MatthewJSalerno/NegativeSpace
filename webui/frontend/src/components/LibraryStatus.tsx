import { useEffect, useState } from "react";
import { api, type LibraryStatus as Status } from "../api";
import { day } from "../format";
import { follow } from "../nav";
import { ACTIVE, CHECK_STARTED, checkResult, noticeClass, stoppedReason } from "../libraryCheck";
import { CheckLibraryDialog } from "./CheckLibraryDialog";

// How often the status follows a running check.
const POLL_MS = 2000;

// The library status at the foot of the sidebar (webui-spec 7.6, ui-design "Page frame"):
// when the source was last indexed and the library last checked. Each line opens its job's
// log; never-checked offers Check library…, which opens the dialog, never a job.
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
  return <section className="library-status" aria-label="Library status">
    <p>{source
      ? <a href={`/logs?run=${source.run_id}`} onClick={go}>Source: indexed {day(source.at)}</a>
      : "Source: not indexed yet"}</p>
    {running && latest && <p className="notice notice-accent" role="status">
      <a href={`/logs?run=${latest.run_id}`} onClick={go}>Library: checking…{progress}</a></p>}
    {stopped && <p className="notice notice-warn">
      <a href={`/logs?run=${stopped.run_id}`} onClick={go}>Library: check on {day(stopped.started_at)} couldn't run</a>; {stoppedReason(stopped)}</p>}
    {!running && (result
      ? <p className={noticeClass(result.tone)}>
          <a href={`/logs?run=${result.run_id}`} onClick={go}>Library: checked {day(result.ended_at ?? result.started_at)} · {checkResult(result)}</a></p>
      : !stopped && <p>Library: not checked yet · <button className="link" onClick={() => setAsking(true)}>Check library…</button></p>)}
    {asking && <CheckLibraryDialog onClose={() => setAsking(false)} />}
  </section>;
}
