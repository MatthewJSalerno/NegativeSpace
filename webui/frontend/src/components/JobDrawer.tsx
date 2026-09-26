import { useEffect, useState } from "react";
import { api, ApiError, type JobState, type Run } from "../api";
import { duration, instant } from "../format";
import { activeTitle, countsLine, currentPhase, phaseLabel, summary, type Connection } from "../jobs";
import { follow, logUrl } from "../nav";

// The operations drawer (webui-spec 4.1): aggregate counts about once a second,
// elapsed time from the job's recorded start, and Cancel. Per-file detail belongs
// to the logs, not here.
// The live progress while a job runs, at the top of the page under the toolbar
// (webui-spec 4.1). When it finishes, FinishedBanner takes its place.
export function JobDrawer({ jobs, connection }: { jobs: JobState; connection: Connection }) {
  const [now, setNow] = useState(Date.now());
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [cancelSent, setCancelSent] = useState<number | null>(null);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const active = jobs.active;
  if (connection === "lost") {
    return (
      <aside className="drawer drawer-lost" role="status">
        Connection lost. The job may still be running. Reconnecting…
      </aside>
    );
  }
  if (!active) return null;

    const phase = currentPhase(active);
    const interrupted = active.presented_status === "Interrupted";
    const cancelling = active.status === "Cancelling" || cancelSent === active.id;
    const started = active.started_at ? Date.parse(active.started_at) : null;
    const percent = phase && phase.total ? Math.min(100, (phase.done / phase.total) * 100) : null;
    const cancel = async () => {
      if (active.id == null) return;
      setCancelError(null);
      try {
        await api.cancelJob(active.id);
        setCancelSent(active.id);
      } catch (error) {
        setCancelError(error instanceof ApiError ? error.message : "The cancel request did not reach the server.");
      }
    };
    return (
      <aside className="drawer" role="status" aria-live="polite">
        <div className="drawer-row">
          <strong>
            {interrupted ? "A job was interrupted" : activeTitle(active)}
            {phase && !interrupted ? ` — ${phaseLabel(phase)}` : ""}
            {phase && phase.total != null && !interrupted ? `: ${phase.done.toLocaleString()} of ${phase.total.toLocaleString()}` : ""}
            {phase && phase.total == null && !interrupted ? `: ${phase.done.toLocaleString()} so far` : ""}
          </strong>
          <span className="muted">
            {interrupted ? "Duration unavailable" : started ? `Elapsed ${duration(now - started)}` : ""}
          </span>
        </div>
        {interrupted ? (
          <p>
            It stopped without finishing, and nothing is running now. The next job you start records it as
            interrupted and settles any file it left mid-way. Started {instant(active.started_at)}.
          </p>
        ) : (
          <>
            <div className={`bar ${percent == null ? "bar-indeterminate" : ""}`}>
              <div style={{ width: percent == null ? undefined : `${percent}%` }} />
            </div>
            {phase && <p className="muted">{countsLine(phase.counts) || "Starting…"}</p>}
            {cancelling && (
              <p>Cancellation requested—waiting for the current work to stop safely.</p>
            )}
            {cancelError && <p className="error">{cancelError}</p>}
            <div className="drawer-actions">
              <button onClick={cancel} disabled={cancelling || !active.cancellable}
                      title={active.cancellable ? undefined : "This job cannot be cancelled from here."}>
                {cancelling ? "Cancelling…" : "Cancel job"}
              </button>
            </div>
          </>
        )}
      </aside>
    );

}

// A finished job's result, at the top of the page under the toolbar, until dismissed.
export function FinishedBanner({ jobs, dismissedId, onDismiss }: {
  jobs: JobState;
  dismissedId: number | null;
  onDismiss: (id: number) => void;
}) {
  // Dismissing a job's banner covers it and every earlier job; a newer one still shows.
  const run = !jobs.active && jobs.last && jobs.last.id != null && (dismissedId == null || jobs.last.id > dismissedId)
    ? jobs.last : null;
  if (!run || !run.outcome) return null;
  const s = summary(run as Run);
  const ended = run.ended_at ? Date.parse(run.ended_at) : null;
  const started = run.started_at ? Date.parse(run.started_at) : null;
  return (
    <div className={`finished-banner finished-${s.tone}`} role="status">
      <div className="drawer-text">
        <strong>{s.headline}</strong>
        <span>{s.detail}</span>
        <span className="muted">
          {started && ended ? `Took ${duration(ended - started)}` : run.status === "Interrupted" ? "Duration unavailable" : ""}
        </span>
      </div>
      <span className="banner-links">
        {(run.outcome.failed > 0 || run.outcome.run_level_issues > 0) && run.id != null && (
          <a href={logUrl({ run: run.id, status: "Failed" })} onClick={follow}>View failures</a>
        )}
        {run.id != null && <a href={logUrl({ run: run.id })} onClick={follow}>View log</a>}
        <button onClick={() => run.id != null && onDismiss(run.id)}>Dismiss</button>
      </span>
    </div>
  );
}
