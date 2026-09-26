import { useEffect, useState } from "react";
import { api, ApiError, type Lineage, type LineageFile, type LineageOperation } from "../api";
import { bytes, instant } from "../format";
import { follow, logUrl } from "../nav";
import { Tip } from "./Tip";

const STEP: Record<string, string> = {
  Pending: "Indexed", Duplicate: "Indexed as a duplicate", Processing: "Started", Completed: "Moved here",
  Copied: "Copied here", Copied_Only: "Copied here, original kept", Failed: "Failed", Removed_Duplicate: "Removed as a duplicate",
  Found_At_Destination: "Found here", Skipped: "Skipped", Cancelled: "Cancelled", Renamed: "Renamed",
};
const PRESENCE: Record<string, string> = { present: "Present", removed: "Removed", missing: "Missing" };
const MODE: Record<string, "index" | "copy" | "move"> = { INDEX: "index", COPY: "copy", MOVE: "move" };

// A photo's lineage as a tree (webui-spec 6.3): one node per file (the source, each copy
// made from it, each exact duplicate), with the steps that happened to it. A file opens
// its photo, a job opens the log there, a failed step opens to its reason and Retry;
// hovering or focusing shows the details. Hovers only reveal: every action is a button.
export function LineageDialog({ photoId, filename, jobRunning, onOpenPhoto, onClose }: {
  photoId: number;
  filename: string;
  jobRunning: boolean;
  onOpenPhoto: (id: number) => void;
  onClose: () => void;
}) {
  const [tree, setTree] = useState<Lineage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.lineage(photoId).then((t) => live && setTree(t),
      (e) => live && setError(e instanceof ApiError ? e.message : "The lineage could not be loaded."));
    return () => { live = false; };
  }, [photoId]);
  // Escape closes this window only: taken on the way down, before the Inspector behind
  // it (which also closes on Escape) can see it.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      onClose();
    };
    document.addEventListener("keydown", key, true);
    return () => document.removeEventListener("keydown", key, true);
  }, [onClose]);

  const retry = async (op: LineageOperation) => {
    const mode = MODE[op.mode ?? ""];
    if (!mode || op.photo_id == null) return;
    try {
      await api.startJob({ mode, file_ids: [op.photo_id] });
      setNotice(`Retrying as a new ${mode === "index" ? "Index" : mode === "copy" ? "Copy" : "Move"}. Its progress shows at the top of the page.`);
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : "The retry could not be started.");
    }
  };

  // Each operation appears once: on the file it produced (a copy's step on the copy),
  // else on the file it acted on (a skip that kept an existing copy, on the source).
  const home = (op: LineageOperation) =>
    (op.files.find((f) => f.role === "destination") ?? op.files.find((f) => f.role === "source") ?? op.files[0])?.file_id;
  const stepsOf = (file: LineageFile) => (tree?.operations ?? []).filter((op) => home(op) === file.file_id);
  // An indexed file records itself as its own origin; a copy records the file it came from.
  const childrenOf = (id: number) => (tree?.files ?? []).filter((f) => f.origin_file_id === id && f.file_id !== id);
  const roots = (tree?.files ?? []).filter((f) => f.origin_kind !== "copy")
    .sort((a, b) => Number(b.photo_id === photoId) - Number(a.photo_id === photoId));

  const node = (file: LineageFile) => {
    const own = file.photo_id === photoId;
    const kind = file.origin_kind === "copy" ? "Copy" : file.origin_kind === "observed_destination" ? "Found at the destination"
      : own ? "Source" : `Duplicate · photo #${file.photo_id}`;
    const details = [
      file.path, file.file_size != null ? bytes(file.file_size) : null,
      file.sha1_hash ? `SHA-1 ${file.sha1_hash.slice(0, 12)}… ${file.matches ? "(same content as this photo)" : "(different content)"}` : null,
      file.created_at ? `Recorded ${instant(file.created_at)}` : null,
    ].filter(Boolean).join("\n");
    return (
      <li key={file.file_id} className={`lineage-node lineage-${file.origin_kind ?? "file"}`}>
        <div className="lineage-file">
          <span className="lineage-kind">{kind}</span>
          <Tip text={details}>
            {file.photo_id != null && !own
              ? <button className="link lineage-path" onClick={() => onOpenPhoto(file.photo_id as number)}
                        title={`Open photo #${file.photo_id}`}><code>{file.path}</code></button>
              : <code className="lineage-path" tabIndex={0}>{file.path}</code>}
          </Tip>
          <span className={`badge presence-${file.presence}`}>{PRESENCE[file.presence ?? ""] ?? file.presence}</span>
        </div>
        <ol className="history-list lineage-steps">
          {stepsOf(file).map((op) => <Step key={op.id} op={op} photoId={photoId} jobRunning={jobRunning} onRetry={retry} />)}
        </ol>
        {childrenOf(file.file_id).length > 0 && (
          <ul className="lineage-children">{childrenOf(file.file_id).map((c) => node(c))}</ul>
        )}
      </li>
    );
  };

  return (
    <div className="overlay lineage-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog lineage-dialog" role="dialog" aria-modal="true" aria-labelledby="lineage-title">
        <header className="lineage-head">
          <h2 id="lineage-title">Lineage of {filename}</h2>
          <button onClick={onClose} aria-label="Close">✕</button>
        </header>
        <p className="muted">
          Every file this photo has been, and every copy of the same content: what happened to each, in which job.
          Hover over a path for its details.
        </p>
        {notice && <p className="notice" role="status">{notice}</p>}
        {error && <p className="error">{error}</p>}
        {!tree && !error && <p className="muted">Loading…</p>}
        {tree && <ul className="lineage-tree">{roots.map((f) => node(f))}</ul>}
        <p><a href={logUrl({ photo: photoId })} onClick={(e) => { onClose(); follow(e); }}>Open in the log</a></p>
      </div>
    </div>
  );
}

function Step({ op, photoId, jobRunning, onRetry }: {
  op: LineageOperation;
  photoId: number;
  jobRunning: boolean;
  onRetry: (op: LineageOperation) => void;
}) {
  const [open, setOpen] = useState(false);
  const failed = op.status === "Failed";
  return (
    <li className={failed ? "history-failed" : undefined}>
      {failed
        ? <button className="link lineage-step" aria-expanded={open} onClick={() => setOpen(!open)}>{STEP.Failed} {open ? "▾" : "▸"}</button>
        : <Tip text={op.error_message ?? `${STEP[op.status] ?? op.status}${op.recovery ? " (recovery of earlier work)" : ""}`}>
            <strong className="lineage-step" tabIndex={0}>{STEP[op.status] ?? op.status}</strong>
          </Tip>}
      <span className="muted"> · <a href={logUrl({ run: op.run_id, photo: photoId })} onClick={follow}
                                  title={`Open job #${op.run_id} in the log`}>job #{op.run_id}{op.mode ? ` ${op.mode.toLowerCase()}` : ""}</a>
        {" · "}{instant(op.timestamp)}</span>
      {failed && open && (
        <div className="lineage-failure">
          <div className="history-detail">{op.error_message ?? "No reason was recorded."}</div>
          {op.photo_id != null && MODE[op.mode ?? ""] && (
            <button onClick={() => onRetry(op)} disabled={jobRunning} title={jobRunning ? "A job is running." : undefined}>
              Retry this photo
            </button>
          )}
        </div>
      )}
    </li>
  );
}
