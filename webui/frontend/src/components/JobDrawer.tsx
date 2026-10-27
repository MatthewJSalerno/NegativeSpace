import type { DismissalState } from "../dismissal";
import { useEffect, useState } from "react";
import { api, ApiError, type BackupStatus, type JobState, type Run } from "../api";
import { duration, instant } from "../format";
import { activeTitle, countsLine, currentPhase, reasonsText, phaseLabel, showsPhotos, summary, type Connection } from "../jobs";
import { Tip } from "./Tip";
import { follow, logUrl } from "../nav";
import { SafetyQuestions } from "./SafetyQuestions";

// The operations drawer (webui-spec 4.1): aggregate counts about once a second,
// elapsed time from the job's recorded start, and Cancel. Per-file detail belongs
// to the logs, not here.
// The live progress while a job runs, at the top of the page under the toolbar
// (webui-spec 4.1). Finished results appear in Notifications; safety decisions stay visible.
export function JobDrawer({ jobs, connection }: { jobs: JobState; connection: Connection }) {
  const [now, setNow] = useState(Date.now());
  const [backupError, setBackupError] = useState<string | null>(null);
  const [backupBusy, setBackupBusy] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [cancelSent, setCancelSent] = useState<number | null>(null);
  const [waiting, setWaiting] = useState<{ id: number | null; since: number } | null>(null);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (jobs.backup?.latest?.outcome === "succeeded") setBackupError(null);
  }, [jobs.backup?.latest?.attempt_id, jobs.backup?.latest?.outcome]);

  const active = jobs.active;
  if (connection === "lost") {
    return (
      <aside className="drawer notice notice-warn" role="status">
        Connection lost. The job may still be running. Reconnecting…
      </aside>
    );
  }
  const retryBackup = async () => {
    setBackupBusy(true); setBackupError(null);
    try { await api.backupNow(); }
    catch (error) { setBackupError(error instanceof ApiError ? error.message : "The backup request could not be confirmed. Check the connection and try again."); }
    finally { setBackupBusy(false); }
  };
  if (!active) return <BackupNotice status={jobs.backup} error={backupError} busy={backupBusy} onRetry={retryBackup} />;
  if (active.backup_stage) return <aside className="drawer notice notice-accent drawer-backup" role="status" aria-live="polite">
    <div className="drawer-row"><strong>{active.backup_stage === "post_job" && active.outcome
      ? `${summary(active).headline} · Backing up catalog…` : "Backing up catalog…"}</strong></div>
    <div className="bar bar-indeterminate"><div /></div>
    <p className="muted">You can browse while this finishes. Photo changes become available afterward.</p>
  </aside>;

    const phase = currentPhase(active);
    const interrupted = active.presented_status === "Interrupted";
    const cancelling = active.status === "Cancelling" || (cancelSent != null && cancelSent === active.id);
    const started = active.started_at ? Date.parse(active.started_at) : null;
    const recorded = phase?.updated_at ? Date.parse(phase.updated_at) : started;
    const lastActivity = Math.max(recorded ?? now, waiting?.id === active.id ? waiting.since : 0);
    // This is a reminder to choose, not a deadline or proof a file is broken.
    const quiet = !interrupted && now - lastActivity >= 120_000;
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
      <>
      <aside className="drawer notice notice-accent" role="status" aria-live="polite">
        <div className="drawer-row">
          <strong>
            {activeTitle(active)}
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
            {phase && <p className="muted">{countsLine(phase.counts, active.mode) || "Starting…"}</p>}
            {quiet && !cancelling && <div className="notice" role="status">
              <strong>No progress recorded for two minutes.</strong>
              <p>A large photo or slow storage may still be working. Keep waiting, or cancel this job. No files are skipped automatically.</p>
              <button onClick={() => setWaiting({ id: active.id, since: now })}>Keep waiting</button>
            </div>}
            {cancelling && (
              <p>Cancellation requested—waiting for the current work to stop safely.
                Recorded results are kept. A blocked storage operation may need the connection restored before it can stop.</p>
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
      {interrupted && <BackupNotice status={jobs.backup} error={backupError} busy={backupBusy} onRetry={retryBackup} />}
      </>
    );

}

// A finished job requiring a safety decision stays visible independently of notification read state.
export function FinishedBanner({ jobs, dismissedId, onDismiss, dismissal, onShowPhotos }: {
  jobs: JobState;
  dismissedId: number | null;
  onDismiss: (id: number) => void;
  dismissal: DismissalState;
  // The Library shows them in place; elsewhere the button is a link to the Library.
  onShowPhotos?: (id: number) => void;
}) {
  // Dismissing a job's banner covers it and every earlier job; a newer one still shows.
  const run = !jobs.active && jobs.last && jobs.last.id != null && (dismissedId == null || jobs.last.id > dismissedId)
    ? jobs.last : null;
  if (!run || !run.outcome || !run.questions?.length) return null;
  const s = summary(run as Run, true);
  const ended = run.ended_at ? Date.parse(run.ended_at) : null;
  const started = run.started_at ? Date.parse(run.started_at) : null;
  return (
    <div className={`finished-banner notice notice-${s.tone}`} role="status">
      <SafetyQuestions key={run.id} run={run} onLeave={() => onDismiss(run.id!)} />
      <div className="drawer-text">
        <strong>{s.headline}</strong>
        {reasonsText(run.outcome) ? <Tip text={reasonsText(run.outcome) as string}><span>{s.detail}</span></Tip>
                                  : <span>{s.detail}</span>}
        <span className="muted">
          {started && ended ? `Took ${duration(ended - started)}` : run.status === "Interrupted" ? "Duration unavailable" : ""}
        </span>
        {dismissal.failedId === run.id && <span className="error" role="alert">Could not save the dismissal. Try again.</span>}
      </div>
      <span className="banner-links">
        {run.id != null && showsPhotos(run as Run) && (onShowPhotos
          ? <button className="link" onClick={() => onShowPhotos(run.id!)}>Show these photos</button>
          : <a href={`/?run=${run.id}`} onClick={follow}>Show these photos</a>)}
        {(run.outcome.failed > 0 || run.outcome.run_level_issues > 0) && run.id != null && (
          <a href={logUrl({ run: run.id, status: "Failed" })} onClick={follow}>View failures</a>
        )}
        {run.id != null && <a href={logUrl({ run: run.id })} onClick={follow}>View log</a>}
        <button disabled={dismissal.pendingId != null} onClick={() => run.id != null && onDismiss(run.id)}>
          {dismissal.pendingId != null ? "Saving…" : dismissal.failedId === run.id ? "Retry dismissal" : "Dismiss"}
        </button>
      </span>
    </div>
  );
}


const BACKUP_REASON: Record<string, string> = {
  insufficient_space: "The backup storage is full. Free some space, then retry.",
  storage_unwritable: "The backup folder is not writable. Fix its permissions, then retry.",
  storage_unavailable: "The backup location is unavailable. Restore access, then retry.",
  storage_not_mounted: "The backup storage is not mounted. Connect it, then retry.",
  storage_overlaps_appdata: "The backup folder overlaps the application data. Choose separate backup storage.",
  verification_failed: "The backup could not be verified. Check the backup storage, then retry.",
  write_failed: "The backup could not be written. Check free space, permissions and the storage connection, then retry.",
};

function BackupNotice({ status, error, busy, onRetry }: {
  status?: BackupStatus | null; error: string | null; busy: boolean; onRetry: () => void;
}) {
  const latest = status?.latest;
  const failed = latest && latest.outcome !== "succeeded";
  if (!error && !failed && !status?.unbacked_count) return null;
  const interrupted = failed && (latest.outcome == null || latest.outcome === "interrupted");
  return <aside className="drawer notice notice-warn backup-notice" role="status">
    <div className="drawer-text">
      <strong>{interrupted ? "Catalog backup did not finish." : failed ? "Catalog backup failed." : "Catalog changes haven’t been backed up."}</strong>
      {failed && <span>{interrupted ? "Back up the current catalog when you’re ready." : BACKUP_REASON[latest.error_category ?? ""] ?? "Open the details, fix the reported problem, then retry."}</span>}
      <button className="link" disabled={busy} onClick={onRetry}>{busy ? "Backing up…" : failed ? "Retry backup" : "Back up now"}</button>
    </div>
    {error && <p className="error">{error}</p>}
    <details><summary>Details</summary>
      <p>{status?.unbacked_count ?? 0} catalog changes are not backed up.
        {status?.last_success ? ` Last successful backup: ${instant(status.last_success)}.` : " No successful backup is recorded."}</p>
      <p>Catalog backups preserve metadata and history, not photo files. Retrying only backs up the catalog; it does not repeat file operations.</p>
      {latest?.error_detail && <p>{latest.error_detail}</p>}
      {latest?.related_run_id != null && <a href={logUrl({ run: latest.related_run_id })} onClick={follow}>View job details</a>}
    </details>
  </aside>;
}
