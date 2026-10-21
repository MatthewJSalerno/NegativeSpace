import { Modal } from "./ui/Modal";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type ActionMode, type Status, type MoveScope, type MovePreview, type MoveSubmission } from "../api";
import { Pager } from "./Pager";
import { plural } from "../format";
import { SubmissionStatus } from "./SubmissionStatus";

type RejectComparison = { last: boolean; rejectedHere: number; onDontAskAgain: () => void };
export type Confirm = { title: string; body: string[]; action: string; danger?: boolean; run: (move?: MoveSubmission) => Promise<void>; move?: MoveScope; onCancel?: () => void;
  reject?: { comparison?: RejectComparison } };

// Every Reject question uses this content and ConfirmDialog. Only an open comparison
// may offer a session preference; rejecting its last Library photo always asks.
export function rejectConfirm(total: number, run: () => Promise<void>, options: {
  filename?: string; onCancel?: () => void; comparison?: RejectComparison;
} = {}): Confirm {
  const one = total === 1;
  const last = options.comparison?.last;
  return {
    title: `Reject ${one ? options.filename ?? "this photo" : plural(total, "photo")}${last ? " too" : ""}?`,
    action: last ? "Reject it too" : "Reject",
    body: [`${one ? "It moves" : "They move"} to the Rejects folder and ${one ? "leaves" : "leave"} your library. You can bring ${one ? "it" : "them"} back any time until you manually empty Rejects.`],
    reject: { comparison: options.comparison },
    run,
    onCancel: options.onCancel,
  };
}

// Copy, Move, Reject or Return to library, for selected photos or a folder (and Copy or
// Move for all of them), asked the same way on every page. "All" counts what the engine
// would take across the whole catalog (GET /status), never a view or search.
export function transferConfirm(mode: ActionMode, status: Status, ids: number[] | { folder: string } | undefined,
                                run: (move?: MoveSubmission) => Promise<void>, onCancel?: () => void, filename?: string,
                                inRejects = false, sourceSubdir?: string): Confirm {
  const scope = Array.isArray(ids) ? (ids.length === 1 && (mode === "reject" || mode === "return") ? "this photo" : plural(ids.length, "selected photo"))
    : ids ? `the photos under ${ids.folder}`
    : mode === "copy" ? `${plural(status.eligible.copy, "ready photo")}`
      : `${plural(status.eligible.move, "ready photo")}`;
  const one = Array.isArray(ids) && ids.length === 1;
  if (mode === "reject") return rejectConfirm(Array.isArray(ids) ? ids.length : 1, () => run(), { filename, onCancel });
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
    move: mode === "move" ? (Array.isArray(ids) ? { file_ids: ids } : sourceSubdir ? { source_subdir: sourceSubdir } : {}) : undefined,
    body: [...(mode === "move" && inRejects ? [
      // A selection in Rejects (webui-spec 2): the warning first, as the review shows only it.
      `${one ? "This photo is" : "These photos are"} in Rejects. Move deletes ${one ? "its original" : "their originals"} from your source once ${one ? "its copy" : "each copy"} in Rejects is verified. ${one ? "That copy becomes the only one" : "Those copies become the only ones"}: empty Rejects and ${one ? "it is" : "they are"} gone.`,
    ] : mode === "move" ? [
      "Unedited photos are copied into the destination's date folders, checked byte for byte, and only then deleted from the source.",
      ...(!ids && status.copied > 0 ? [`${plural(status.copied, "photo is", "photos are")} already copied: each of their copies is verified again before its source is deleted.`] : []),
      ...(!ids && status.rejected_with_source > 0 ? [`${plural(status.rejected_with_source, "rejected photo still has its source", "rejected photos still have their sources")}: each source is deleted once its copy in Rejects is verified, and that copy becomes the only one: empty Rejects and it is gone.`] : []),
      "Duplicate copies in the source are removed once a matching copy is confirmed at the destination.",
    ] : [
      "Each photo is copied into the destination's date folders and checked byte for byte. Nothing in the source is changed or deleted.",
    ]), ...(!ids && !sourceSubdir && status.held ? [`${plural(status.held, "source file needs", "source files need")} attention and will stay in the source. Find them in Not organized → Needs attention.`] : [])],
    run,
    onCancel,
  };
}

export function ConfirmDialog({ confirm, onClose }: { confirm: Confirm; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const [dontAsk, setDontAsk] = useState(false);
  const comparison = confirm.reject?.comparison;
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<MovePreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [choice, setChoice] = useState<"include" | "leave" | "">("");
  const [page, setPage] = useState(1);
  useEffect(() => {
    if (!confirm.move) return;
    let alive = true;
    setPreview(null); setPreviewError(null); setError(null); setChoice(""); setPage(1);
    api.previewMove(confirm.move).then(result => { if (alive) setPreview(result); })
      .catch(e => { if (alive) setPreviewError(e instanceof ApiError ? e.message : "The Move selection could not be checked."); });
    return () => { alive = false; };
  }, [confirm.move, refresh]);
  const edited = preview?.edited_originals ?? [];
  const waiting = !!confirm.move && (!preview || !preview.file_ids.length || (edited.length > 0 && !choice));
  const cancel = useCallback(() => { confirm.onCancel?.(); onClose(); }, [confirm, onClose]);
  return (
    <Modal role="alertdialog" labelledBy="confirm-title" onClose={cancel} busy={busy}>
        <h2 id="confirm-title">{confirm.title}</h2>
        {confirm.body.map((line) => <p key={line}>{line}</p>)}
        {comparison?.last && <p className="reject-last">
          <strong>None of these photos would be left in the library.</strong>
          {comparison.rejectedHere > 0 ? ` You have rejected ${comparison.rejectedHere === 1 ? "its look-alike" : `its ${comparison.rejectedHere} look-alikes`} in this comparison; this is the last one.` : ""}
        </p>}
        {comparison && !comparison.last && <label className="checkbox-row">
          <input type="checkbox" checked={dontAsk} disabled={busy} onChange={e => setDontAsk(e.target.checked)} />
          Don't ask again while comparing
        </label>}
        {confirm.move && <section aria-label="Source originals">
          {!preview && !previewError && <p role="status">Checking the Move selection…</p>}
          {previewError && <p className="error" role="alert">{previewError}</p>}
          {preview && preview.file_ids.length === 0 && <p>There are no catalogued photos in this source selection.</p>}
          {preview && preview.rejected_originals > 0 && <p className="warning">{plural(preview.rejected_originals, "original has its retained copy", "originals have their retained copies")} in Rejects. Removing the source leaves only that copy; emptying Rejects will remove it.</p>}
          {edited.length > 0 && <>
            <h3>Originals with edited copies</h3>
            <p>{plural(edited.length, "source original has an edited copy", "source originals have edited copies")} at the destination.
              The edited versions and recorded original metadata history stay. <strong>Exact original photo bytes are not retained if you include these originals.</strong></p>
            <details><summary>Show {plural(edited.length, "affected original")}</summary>
              <ul>{edited.slice((page - 1) * 20, page * 20).map(photo => <li key={photo.photo_id}>
                <strong>{photo.filename}</strong>{photo.in_rejects && " (in Rejects)"}<br /><span className="muted">Source: {photo.source}</span>
              </li>)}</ul>
              {edited.length > 20 && <Pager page={page} pages={Math.ceil(edited.length / 20)} total={edited.length}
                pageSize={20} sizes={[20]} onPage={setPage} onPageSize={() => {}} />}
            </details>
            <fieldset disabled={busy}><legend>For this Move only (required)</legend>
              <label className="checkbox-row"><input type="radio" name="edited-originals" required checked={choice === "include"}
                onChange={() => setChoice("include")} />Include {plural(edited.length, "original")}</label>
              <label className="checkbox-row"><input type="radio" name="edited-originals" required checked={choice === "leave"}
                onChange={() => setChoice("leave")} />Leave these originals at source</label>
            </fieldset>
            <p className="muted">Other photos in this selection follow the normal Move checks. Every included original is verified before removal. This choice is not saved for future jobs.</p>
          </>}
          {(previewError || error) && <button className="primary" disabled={busy} onClick={() => setRefresh(n => n + 1)}>Refresh Move preview</button>}
        </section>}
        {busy && <SubmissionStatus />}
        {error && <p className="error" role="alert">{error}</p>}
        <footer className="settings-actions">
          <button data-initial-focus onClick={cancel} disabled={busy}>Cancel</button>
          <button className={confirm.danger ? "danger" : "primary"} disabled={busy || waiting}
                  onClick={async () => {
                    setBusy(true); setError(null);
                    try {
                      if (dontAsk && comparison && !comparison.last) comparison.onDontAskAgain();
                      await confirm.run(preview ? { mode: "move", file_ids: preview.file_ids,
                        move_preview_token: preview.token, confirm_edited_sources: choice === "include" } : undefined);
                      onClose();
                    }
                    catch (e) { setError(e instanceof ApiError ? e.message : "The action could not be completed. Check its status before trying again."); }
                    finally { setBusy(false); }
                  }}>
            {confirm.action}
          </button>
        </footer>
    </Modal>
  );
}
