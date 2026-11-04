import { useEffect, useState } from "react";
import { api, ApiError, type LibraryStatus } from "../api";
import { day } from "../format";
import { follow } from "../nav";
import { CHECK_STARTED, checkResult, depthName } from "../libraryCheck";
import { Modal } from "./ui/Modal";
import { SubmissionStatus } from "./SubmissionStatus";

// Check library (webui-spec 7.6): the menu item and the sidebar status open this, never
// starting a check themselves. It explains the two depths and shows the last result.
export function CheckLibraryDialog({ onClose }: { onClose: () => void }) {
  const [status, setStatus] = useState<LibraryStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.libraryStatus().then(s => live && setStatus(s), () => live && setStatus(null));
    return () => { live = false; };
  }, []);
  const start = async (depth: "quick" | "thorough") => {
    setBusy(true); setError(null);
    try {
      await api.checkLibrary(depth);
      window.dispatchEvent(new Event(CHECK_STARTED));
      onClose();
    } catch (e) { setError(e instanceof ApiError ? e.message : "The check could not be started. Check its status before trying again."); }
    finally { setBusy(false); }
  };
  const last = status?.result;
  return <Modal labelledBy="check-library-title" onClose={onClose} busy={busy}>
    <h2 id="check-library-title">Check library</h2>
    <p>Looks for photos that are missing, moved, changed or damaged in the library, and for files NegativeSpace didn't put there. Nothing is changed.</p>
    <dl className="check-depths">
      <dt>Quick check</dt>
      <dd>Compares each file's size and modified date with what was recorded, and reads only the files that differ. Usually minutes.</dd>
      <dt>Thorough check</dt>
      <dd>Reads every file and compares its checksum, which also finds files damaged on disk. About as long as copying the whole library once.</dd>
    </dl>
    <p>Last checked: {last
      ? <a href={`/logs?run=${last.run_id}`} onClick={e => { onClose(); follow(e); }}>{day(last.ended_at ?? last.started_at)} · {depthName(last.depth)} · {checkResult(last)}</a>
      : status ? "not checked yet" : "…"}</p>
    {busy && <SubmissionStatus />}
    {error && <p className="error" role="alert">{error}</p>}
    <footer className="settings-actions">
      <button onClick={onClose} disabled={busy}>Cancel</button>
      <button onClick={() => void start("thorough")} disabled={busy}>Thorough check</button>
      <button className="primary" data-initial-focus onClick={() => void start("quick")} disabled={busy}>Quick check</button>
    </footer>
  </Modal>;
}
