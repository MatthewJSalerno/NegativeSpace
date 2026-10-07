import { useEffect, useState } from "react";
import { api, type BrowseFilters, type PhotoPosition, type Sort } from "../api";
import type { ComparisonState } from "../comparisonState";

export type SetBrowse = BrowseFilters & { sort: Sort; page_size: number };
export type SetActions = {
  setBrowse?: SetBrowse;
  onOpenSet?: (reference: number, candidate: number | null) => void;
  onShowSet?: (reference: number, threshold: number) => void;
};

export function ReviewActions({ workspace, busy, setBrowse, onOpenSet, onShowSet }: SetActions & {
  workspace: ComparisonState; busy: boolean;
}) {
  const [position, setPosition] = useState<PhotoPosition | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [copying, setCopying] = useState(false);
  const [copied, setCopied] = useState(false);
  const [manualLink, setManualLink] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setPosition(null); setError(null);
    if (setBrowse) api.photoPosition({ ...setBrowse, photo_id: workspace.origin }).then(
      result => { if (live) setPosition(result); },
      () => { if (live) setError("Set navigation could not be loaded."); });
    return () => { live = false; };
  }, [setBrowse, workspace.origin, retry]);
  const bookmark = JSON.stringify(workspace);
  useEffect(() => { setCopied(false); setManualLink(null); }, [bookmark]);
  const copy = async () => {
    const url = new URL(window.location.href);
    url.pathname = "/";
    url.searchParams.delete("review_photo");
    url.searchParams.set("photo", String(workspace.origin));
    url.searchParams.set("tab", "similar");
    url.searchParams.set("review", JSON.stringify(workspace));
    setCopying(true); setCopied(false); setManualLink(null);
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(url.href);
      setCopied(true);
    } catch { setManualLink(url.href); }
    finally { setCopying(false); }
  };
  return <div>
    <div className="photo-actions">
      <button disabled={busy || copying} onClick={copy}>Copy review link</button>
      {onShowSet && <button disabled={busy} onClick={() => onShowSet(workspace.reference, workspace.threshold)}>Show this set in gallery</button>}
      {setBrowse && onOpenSet && <>
        <button disabled={busy || position?.previous_id == null} onClick={() => onOpenSet(position!.previous_id!, null)}>Previous set</button>
        <button disabled={busy || position?.next_id == null} onClick={() => onOpenSet(position!.next_id!, null)}>Next set</button>
      </>}
    </div>
    {copied && <p role="status">Review link copied. It opens this comparison for people who can access this library.</p>}
    {manualLink && <label>Copy this review link manually
      <input aria-label="Review link" readOnly value={manualLink} onFocus={e => e.target.select()} />
    </label>}
    {error && <p className="error" role="alert">{error} <button onClick={() => setRetry(n => n + 1)}>Retry set navigation</button></p>}
    {setBrowse && position?.position === null && <p className="section-note">This reference is outside the current gallery sets. Return to the gallery to choose a set.</p>}
    {setBrowse && <p className="section-note">Set navigation follows the gallery’s percentage, filters and sort. Viewing rotations are temporary and reset when leaving this set.</p>}
  </div>;
}
