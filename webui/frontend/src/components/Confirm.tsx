import { useCallback, useEffect, useState } from "react";
import type { Status } from "../api";
import { count, plural } from "../format";

export type Confirm = { title: string; body: string[]; action: string; danger?: boolean; run: () => Promise<void>; onCancel?: () => void };

// Copy or Move, for selected photos or all of them, asked the same way on every page.
// "All" counts what the engine would take across the whole catalog (GET /status),
// never a view or search.
export function transferConfirm(mode: "copy" | "move", status: Status, ids: number[] | undefined,
                                run: () => Promise<void>, onCancel?: () => void): Confirm {
  const scope = ids ? plural(ids.length, "selected photo")
    : mode === "copy" ? `every photo not yet copied (${count(status.eligible.copy)})`
      : `every photo not yet moved (${count(status.eligible.move)})`;
  return {
    title: mode === "move" ? `Move ${scope}?` : `Copy ${scope}?`,
    action: mode === "move" ? "Move" : "Copy",
    danger: mode === "move",
    body: mode === "move" ? [
      "Each photo is copied into the destination's date folders, checked byte for byte, and only then deleted from the source.",
      ...(!ids && status.copied > 0 ? [`${plural(status.copied, "photo is", "photos are")} already copied: each of their copies is verified again before its source is deleted.`] : []),
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
  const cancel = useCallback(() => { confirm.onCancel?.(); onClose(); }, [confirm, onClose]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && cancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cancel]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && cancel()}>
      <div className="dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title">
        <h2 id="confirm-title">{confirm.title}</h2>
        {confirm.body.map((line) => <p key={line}>{line}</p>)}
        <footer className="settings-actions">
          <button onClick={cancel} disabled={busy}>Cancel</button>
          <button className={confirm.danger ? "danger" : "primary"} disabled={busy}
                  onClick={async () => { setBusy(true); await confirm.run(); onClose(); }}>
            {confirm.action}
          </button>
        </footer>
      </div>
    </div>
  );
}
