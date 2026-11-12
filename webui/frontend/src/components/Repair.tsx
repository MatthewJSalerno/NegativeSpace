import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, type RepairItem, type RepairKind, type RepairPreview } from "../api";
import { useJobFeed } from "../jobs";
import { plural } from "../format";
import { Modal } from "./ui/Modal";
import { SubmissionStatus } from "./SubmissionStatus";

// Repair (webui-spec 7.6): one dialog for the selection bar and one photo's Inspector, kept
// outside the panes that open it so a layout change does not lose it.
const RepairContext = createContext<((ids: number[]) => void) | null>(null);
export function RepairProvider({ children }: { children: ReactNode }) {
  const [ids, setIds] = useState<number[] | null>(null);
  return <RepairContext.Provider value={selected => setIds([...selected])}>
    {children}
    {ids && <RepairDialog ids={ids} onClose={() => setIds(null)} />}
  </RepairContext.Provider>;
}

export function RepairButton({ ids, count }: { ids: number[]; count?: number }) {
  const open = useContext(RepairContext);
  const { jobs } = useJobFeed();
  const running = jobs.active != null && jobs.active.presented_status !== "Interrupted";
  return <button className="photo-action" disabled={running} title={running ? "Wait for the running job to finish." : undefined}
    onClick={() => open?.(ids)}>{count != null ? `Repair (${count})…` : "Repair…"}</button>;
}

type Group = RepairPreview["groups"][number];
// Each kind of fix, as its group reads: what was found and where it goes. A kept version is
// filed by its date, so its group says whether it stays or moves (webui-spec 7.6).
const where = (g: Group) => `${g.items.every(i => i.stays) ? "stays in" : "moves to"} ${g.folder}`;
const FIX: Record<RepairKind, (g: Group) => string> = {
  move_back: g => `${plural(g.items.length, "photo")} in the wrong folder → move back to ${g.folder}`,
  from_rejects: g => `${plural(g.items.length, "photo")} in Rejects → move back to ${g.folder}`,
  copy_back: g => `${plural(g.items.length, "photo")} missing, a copy is in the source → copy back to ${g.folder}`,
  keep_new: g => `${plural(g.items.length, "photo")} changed, looks the same → keep the new version (${where(g)})`,
  edit: g => `${plural(g.items.length, "photo")} replaced by a different picture → It's an edit of this photo: keep the new version (${where(g)})`,
};
const KEEPS: RepairKind[] = ["keep_new", "edit"];
const key = (g: { repair: RepairKind; folder: string }) => `${g.repair}:${g.folder}`;
const fileLine = (g: Group, i: RepairItem) => g.repair === "copy_back" ? `From the source → ${i.to_relative}`
  : i.stays ? `${i.from_relative} (stays)` : `${i.from_relative} → ${i.to_relative}`;

function RepairDialog({ ids, onClose }: { ids: number[]; onClose: () => void }) {
  const [preview, setPreview] = useState<RepairPreview | null>(null);
  const [error, setError] = useState("");
  const [unticked, setUnticked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [copied, setCopied] = useState<"done" | "manual" | null>(null);
  const { jobs } = useJobFeed();
  const running = jobs.active != null && jobs.active.presented_status !== "Interrupted";
  useEffect(() => {
    let live = true;
    setPreview(null); setError(""); setUnticked(new Set());
    // It's an edit overrides what the check found, so the user ticks it (webui-spec 7.6).
    api.repairPreview(ids).then(p => {
      if (live) { setPreview(p); setUnticked(new Set(p.groups.filter(g => g.repair === "edit").map(key))); }
    },
      e => { if (live) setError(e instanceof Error ? e.message : "What Repair would do could not be worked out."); });
    return () => { live = false; };
  }, [JSON.stringify(ids), reload]);
  const chosen = preview?.groups.filter(g => !unticked.has(key(g))).flatMap(g => g.items.map(i => i.photo_id)) ?? [];
  const total = preview ? preview.fixes + preview.cannot.length : 0;
  const cannot = groupBy(preview?.cannot ?? [], i => i.todo ?? "");
  const list = (preview?.unreadable ?? []).map(u => u.path).join("\n");
  const start = async () => {
    if (!preview?.check_run) return;
    setBusy(true); setError("");
    try {
      await api.repair(chosen, preview.check_run);
      window.dispatchEvent(new Event("ns-review-changed"));
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Repair could not be started. Check its status before trying again.");
      if (e instanceof ApiError && e.code === "repair_preview_changed") setReload(n => n + 1);
    } finally { setBusy(false); }
  };
  const copyList = async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(list);
      setCopied("done");
    } catch { setCopied("manual"); }
  };
  return <Modal labelledBy="repair-title" onClose={onClose} busy={busy}>
    <h2 id="repair-title">{preview ? `Repair ${plural(total, "photo")}?` : "Repair"}</h2>
    {!preview && !error && <p role="status">Working out what Repair would do…</p>}
    {preview && total === 0 && <p>The latest library check found nothing to repair for {ids.length === 1 ? "this photo" : "these photos"}.</p>}
    {preview && preview.groups.length > 0 && <section className="repair-group" aria-labelledby="repair-fixed">
      <h3 id="repair-fixed">Will be fixed</h3>
      <p className="section-note">Each file is checked again just before it moves; one that changed since the check is left alone and reported. Nothing is deleted.</p>
      {preview.groups.map(g => <div className="repair-fix" key={key(g)}>
        <label className="checkbox-row">
          <input type="checkbox" checked={!unticked.has(key(g))} disabled={busy}
            onChange={e => setUnticked(s => { const n = new Set(s); if (e.target.checked) n.delete(key(g)); else n.add(key(g)); return n; })} />
          {FIX[g.repair](g)}
        </label>
        {g.repair === "edit" && <p className="section-note">The check found a different picture, so this is unticked.
          Tick it only if the file is an edit of the photo.</p>}
        {KEEPS.includes(g.repair) && g.folder.startsWith("Undated/") && <p className="section-note">No date in the
          file, so it's filed by its original file time. Once it's kept, Edit metadata date… in its Inspector gives it a date.</p>}
        <details><summary>Show {g.items.length === 1 ? "the file" : "the files"}</summary>
          <ul className="repair-files">{g.items.map(i => <li key={i.photo_id}>{fileLine(g, i)}</li>)}</ul>
        </details>
      </div>)}
    </section>}
    {preview && preview.cannot.length > 0 && <section className="repair-group" aria-labelledby="repair-cannot">
      <h3 id="repair-cannot">Can't be fixed here (nothing will be done)</h3>
      {[...cannot].map(([todo, items]) => <div className="repair-fix" key={todo}>
        <p><strong>{plural(items.length, "photo")}</strong>: {todo}</p>
        {items.some(i => i.index_source) && <button disabled={busy || running} onClick={async () => {
          setBusy(true); setError("");
          try { await api.startJob({ mode: "index" }); onClose(); }
          catch (e) { setError(e instanceof Error ? e.message : "The Index could not be started. Check its status before trying again."); }
          finally { setBusy(false); }
        }}>Index source</button>}
        <details><summary>Show {items.length === 1 ? "the photo" : "the photos"}</summary>
          <ul className="repair-files">{items.map(i => <li key={i.photo_id}>{i.relative}: {i.what}</li>)}</ul>
        </details>
      </div>)}
      {preview.unreadable.length > 0 && <div className="repair-fix">
        <details><summary>Show these files ({preview.unreadable.length})</summary>
          <ul className="repair-files">{preview.unreadable.map(u => <li key={u.path}><code>{u.path}</code>{u.reason ? ` (${u.reason})` : ""}</li>)}</ul>
          <p className="section-note">Paths are from the destination folder you chose in Settings.</p>
        </details>
        <button disabled={busy} onClick={() => void copyList()}>Copy list</button>
        {copied === "done" && <p role="status">The list is copied, one file per line.</p>}
        {copied === "manual" && <><p role="status">The browser didn't allow copying. Select the list and copy it:</p>
          <textarea className="repair-list" readOnly rows={Math.min(8, preview.unreadable.length)} value={list}
            onFocus={e => e.currentTarget.select()} aria-label="Unreadable files" /></>}
      </div>}
    </section>}
    {busy && <SubmissionStatus />}
    {error && <p className="error" role="alert">{error}</p>}
    <footer className="settings-actions">
      <button data-initial-focus onClick={onClose} disabled={busy}>Cancel</button>
      {preview && preview.fixes > 0 && <button className="primary" disabled={busy || running || chosen.length === 0}
        title={running ? "Wait for the running job to finish." : undefined} onClick={() => void start()}>
        Repair {chosen.length}</button>}
    </footer>
  </Modal>;
}

function groupBy(items: RepairItem[], by: (i: RepairItem) => string): Map<string, RepairItem[]> {
  const out = new Map<string, RepairItem[]>();
  for (const i of items) out.set(by(i), [...(out.get(by(i)) ?? []), i]);
  return out;
}
