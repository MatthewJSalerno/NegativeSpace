import { Modal } from "./ui/Modal";
import { useCallback, useState } from "react";
import type { ActionMode, Status } from "../api";
import { count, plural } from "../format";
import { SubmissionStatus } from "./SubmissionStatus";

export type Confirm = { title: string; body: string[]; action: string; danger?: boolean; run: () => Promise<void>; onCancel?: () => void };

// Copy, Move, Reject or Return to library, for selected photos or a folder (and Copy or
// Move for all of them), asked the same way on every page. "All" counts what the engine
// would take across the whole catalog (GET /status), never a view or search.
export function transferConfirm(mode: ActionMode, status: Status, ids: number[] | { folder: string } | undefined,
                                run: () => Promise<void>, onCancel?: () => void): Confirm {
  const scope = Array.isArray(ids) ? (ids.length === 1 && (mode === "reject" || mode === "return") ? "this photo" : plural(ids.length, "selected photo"))
    : ids ? `the photos under ${ids.folder}`
    : mode === "copy" ? `every photo not yet copied (${count(status.eligible.copy)})`
      : `every photo not yet moved (${count(status.eligible.move)})`;
  const one = Array.isArray(ids) && ids.length === 1;
  if (mode === "reject") return {
    title: `Reject ${scope}?`,
    action: "Reject",
    body: [`${one ? "It moves" : "They move"} out of the library into the Rejects folder. Nothing is deleted, and you can return ${one ? "it" : "them"} until you empty Rejects.`],
    run,
    onCancel,
  };
  if (mode === "return") return {
    title: `Return ${scope} to the library?`,
    action: "Return to library",
    body: [`${one ? "It moves" : "They move"} back to ${one ? "its date folder" : "their date folders"} in the library.`],
    run,
    onCancel,
  };
  return {
    title: mode === "move" ? `Move ${scope}?` : `Copy ${scope}?`,
    action: mode === "move" ? "Move" : "Copy",
    danger: mode === "move",
    body: mode === "move" ? [
      "Each photo is copied into the destination's date folders, checked byte for byte, and only then deleted from the source.",
      ...(!ids && status.copied > 0 ? [`${plural(status.copied, "photo is", "photos are")} already copied: each of their copies is verified again before its source is deleted.`] : []),
      ...(!ids && status.rejected_with_source > 0 ? [`${plural(status.rejected_with_source, "rejected photo still has its source", "rejected photos still have their sources")}: each source is deleted once its copy in Rejects is verified.`] : []),
      "Duplicate copies in the source are removed once a matching copy is confirmed at the destination.",
    ] : [
      "Each photo is copied into the destination's date folders and checked byte for byte. Nothing in the source is changed or deleted.",
    ],
    run,
    onCancel,
  };
}

export function ConfirmDialog({ confirm, onClose }: { confirm: Confirm; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cancel = useCallback(() => { confirm.onCancel?.(); onClose(); }, [confirm, onClose]);
  return (
    <Modal role="alertdialog" labelledBy="confirm-title" onClose={cancel} busy={busy}>
        <h2 id="confirm-title">{confirm.title}</h2>
        {confirm.body.map((line) => <p key={line}>{line}</p>)}
        {busy && <SubmissionStatus />}
        {error && <p className="error" role="alert">{error}</p>}
        <footer className="settings-actions">
          <button data-initial-focus onClick={cancel} disabled={busy}>Cancel</button>
          <button className={confirm.danger ? "danger" : "primary"} disabled={busy}
                  onClick={async () => {
                    setBusy(true); setError(null);
                    try { await confirm.run(); onClose(); }
                    catch { setError("The action could not be completed. Check its status before trying again."); }
                    finally { setBusy(false); }
                  }}>
            {confirm.action}
          </button>
        </footer>
    </Modal>
  );
}
