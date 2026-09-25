import { useEffect, useState } from "react";
import { api, ApiError, type BackupAttempt, type Backups } from "../api";
import { bytes, instant, plural } from "../format";

const ZSTD = "https://facebook.github.io/zstd/";
const ZSTD_RELEASES = "https://github.com/facebook/zstd/releases";

function trigger(b: BackupAttempt): string {
  if (b.trigger_kind === "manual") return "Manual";
  if (b.trigger_kind === "post_job") return b.related_run_id ? `After job #${b.related_run_id}` : "After a job";
  return "Before a change";
}

function format(b: BackupAttempt): string {
  if (!b.relative_filename) return "—";
  return b.compression_format === "zstd" ? "Zstandard, .db.zst" : b.compression_format ? b.compression_format : "Not compressed, .db";
}

// The file's state, or a download link for a usable backup. A file that is gone
// keeps its history but is never offered as a recovery copy (webui-spec 9).
function fileState(b: BackupAttempt) {
  if (b.outcome === null) return <span className="muted">In progress</span>;
  if (b.outcome === "interrupted") return <span className="warning">Interrupted - no usable file</span>;
  if (b.outcome === "failed") return <span className="error">Failed: {b.error_detail ?? b.error_category}</span>;
  switch (b.availability) {
    case "present": return <a href={api.backupDownloadUrl(b.attempt_id)} download>Download</a>;
    case "pruned": return <span className="muted">Removed by the retention limit</span>;
    case "unknown": return <span className="warning">Backup storage cannot be read</span>;
    default: return <span className="muted">Backup file no longer available</span>;
  }
}

// Catalog backups (webui-spec 9): the list, Back up now and downloads, with how to
// open and restore a backup. Shown inside Settings; `retentionDraft` is the value
// being edited there, so lowering it says what it would remove before it is saved.
export function BackupsPanel({ retentionDraft }: { retentionDraft: number }) {
  const [data, setData] = useState<Backups | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "error" | "ok"; text: string } | null>(null);

  const load = () => api.backups().then(setData, (e) =>
    setMessage({ kind: "error", text: e instanceof ApiError ? e.message : "The backup list could not be loaded." }));

  useEffect(() => {
    load();
  }, []);

  // While a job runs, look again until it ends: it takes its own backup, and then
  // Back up now becomes available without reopening Settings.
  useEffect(() => {
    if (!data?.job_active) return;
    const timer = window.setTimeout(load, 2000);
    return () => window.clearTimeout(timer);
  }, [data]);

  const backUpNow = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const made = await api.backupNow();
      setMessage(made.outcome === "succeeded"
        ? { kind: "ok", text: `Backed up: ${made.relative_filename} (${bytes(made.size)}), verified.` }
        : { kind: "error", text: `The backup failed: ${made.error_detail ?? made.error_category}. Nothing else was changed.` });
    } catch (e) {
      setMessage({ kind: "error", text: e instanceof ApiError ? e.message : "The backup could not be started." });
    } finally {
      setBusy(false);
      load();
    }
  };

  if (!data) return message ? <p className="error" role="alert">{message.text}</p> : <p className="muted">Loading backups…</p>;

  const removed = Number.isInteger(retentionDraft) && retentionDraft > 0 && retentionDraft < data.retention
    ? Math.max(0, data.automatic_retained - retentionDraft) : 0;

  return (
    <div className="backups">
      <p className="notice">
        <strong>Catalog backups hold recorded file information, metadata and history, not photos.</strong>{" "}
        They cannot recreate or recover a photo. Keep separate backups of your photos.
      </p>

      {!data.storage.ok && (
        <p className="error" role="alert">
          Backups cannot be written: {data.storage.error_detail}. Correct the <code>/backups</code> mount in the
          Docker setup; it must be separate storage from <code>/appdata</code>.
        </p>
      )}
      {data.unbacked.count > 0 && (
        <p className="warning">
          {plural(data.unbacked.count, "catalog change")} {data.unbacked.count === 1 ? "is" : "are"} not backed up yet
          {data.unbacked.runs.length > 0 && <> (from {data.unbacked.runs.map((r) => `job #${r}`).join(", ")})</>}.
          {" "}{data.last_success ? <>Last successful backup: {instant(data.last_success)}.</> : <>There is no successful backup.</>}
        </p>
      )}

      <div className="field-inline">
        <button onClick={backUpNow} disabled={busy || data.job_active}
                title={data.job_active ? "Wait for the running job to finish - it takes its own backup when it ends." : undefined}>
          {busy ? "Backing up…" : "Back up now"}
        </button>
        <span className="muted">
          {data.job_active
            ? "A job is running; it takes its own backup when it ends."
            : <>{plural(data.present_count, "backup")} on disk, {bytes(data.present_bytes)}.
                {" "}Last successful: {data.last_success ? instant(data.last_success) : "none yet"}.</>}
        </span>
      </div>
      {message && <p className={message.kind} role="alert">{message.text}</p>}
      {removed > 0 && (
        <p className="warning">
          Saving a limit of {retentionDraft} removes the {plural(removed, "oldest automatic backup")} after the next
          backup succeeds. Manual backups are never removed.
        </p>
      )}

      {data.items.length === 0 ? <p className="muted">No backups yet.</p> : (
        <table className="log-table backup-table">
          <thead><tr><th>When</th><th>Trigger</th><th>Size</th><th>Format</th><th>File</th></tr></thead>
          <tbody>
            {data.items.map((b) => (
              <tr key={b.attempt_id}>
                <td className="nowrap">{instant(b.started_at)}</td>
                <td>{trigger(b)}</td>
                <td className="nowrap">{b.size == null ? "—" : bytes(b.size)}</td>
                <td>{format(b)}</td>
                <td>{fileState(b)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <details>
        <summary>Opening a downloaded backup</summary>
        <p>
          New backups are compressed with Zstandard (<a href={ZSTD} target="_blank" rel="noreferrer">{ZSTD}</a>).
          The format of each one is in the list above. Decompressed, the file is the catalog database itself: it can be
          placed as <code>ns_sqlite.db</code> without any other conversion.
        </p>
        <table className="log-table">
          <thead><tr><th>Format</th><th>Decompress</th><th>Where to get a tool</th></tr></thead>
          <tbody>
            <tr><td>Not compressed, <code>.db</code></td><td>Nothing to do</td><td>—</td></tr>
            <tr>
              <td>Zstandard, <code>.db.zst</code></td>
              <td><code className="copyable">zstd -d &lt;file&gt;</code></td>
              <td>
                Linux: the <code>zstd</code> package (<code>apt install zstd</code>, <code>dnf install zstd</code>).
                macOS: <code>brew install zstd</code>. Windows: the <code>win64</code> zip
                from <a href={ZSTD_RELEASES} target="_blank" rel="noreferrer">the Zstandard releases</a>, or 7-Zip with
                Zstandard, or WinRAR. The <a href={ZSTD} target="_blank" rel="noreferrer">project page</a> lists more.
              </td>
            </tr>
          </tbody>
        </table>
      </details>
      <details>
        <summary>Restoring a backup</summary>
        <p>There is no restore button: restoring replaces the catalog, so it is done by hand.</p>
        <ol>
          <li>Stop the application container.</li>
          <li>Keep the current <code>ns_sqlite.db</code> and any <code>ns_sqlite.db-wal</code> and <code>ns_sqlite.db-shm</code> beside it
              somewhere safe.</li>
          <li>Decompress the backup if it is a <code>.db.zst</code> (<code>zstd -d &lt;file&gt;</code>).</li>
          <li>Put it at <code>/appdata/db/ns_sqlite.db</code>, with no old <code>-wal</code> or <code>-shm</code> files beside it,
              and check its owner and permissions match the old file.</li>
          <li>Start the application.</li>
        </ol>
        <p className="warning">
          Restoring the catalog does not undo any change to photos or recreate them, and the restored catalog may not
          match what is on the destination now.
        </p>
      </details>
    </div>
  );
}
