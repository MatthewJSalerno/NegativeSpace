import { useRef } from "react";
import { placeOf, type Place, type PhotoItem } from "../api";
import { epoch, isFallbackDate, photoDate, plural } from "../format";
import { Thumb } from "./Thumb";

const STATUS_BADGE: Record<string, string> = {
  Completed: "Moved", Copied: "Copied", Found_At_Destination: "At destination", Failed: "Failed",
  Processing: "In progress", Rejected: "Rejected", Rejected_Copied: "Rejected",
};

export function Gallery({ page: shown, pageOf, refreshKey, selected, place, selectable, openId, onOpen, onToggle, onToggleMany, matchThreshold, onReviewSet, onExploreSet, keepItem }: {
  // Keep this one, reject the rest: the kept photo comes first, full size, marked
  // Keeping, with no tick box, so it cannot be rejected with the rest.
  keepItem?: PhotoItem | null;
  page: { items: PhotoItem[] };
  // The page each photo came from, so scrolling can tell which page is on top.
  pageOf?: number[];
  matchThreshold?: number;
  onReviewSet?: (id: number) => void; onExploreSet?: (id: number) => void;
  refreshKey: number;
  selected: Set<number>;
  // The selection's place: a photo of the other place cannot join it (webui-spec 2).
  place: Place | null;
  selectable: boolean;
  openId: number | null;
  onOpen: (id: number) => void;
  onToggle: (item: PhotoItem, on: boolean) => void;
  onToggleMany: (items: PhotoItem[], on: boolean) => void;
}) {
  const anchor = useRef<number | null>(null);
  const keepId = keepItem?.id;
  const page = keepItem ? { items: [keepItem, ...shown.items.filter((item) => item.id !== keepId)] } : shown;
  // The kept card is not one of the loaded pages' photos.
  const pageOfShown = keepItem ? [pageOf?.[0], ...(pageOf ?? [])] : pageOf;

  // Shift-click selects the range from the last photo clicked, on this page.
  const toggle = (index: number, shift: boolean) => {
    const item = page.items[index];
    if (item.id === keepId) return;
    const on = !selected.has(item.id);
    if (shift && anchor.current != null) {
      const [a, b] = [anchor.current, index].sort((x, y) => x - y);
      onToggleMany(page.items.slice(a, b + 1).filter((i) => i.id !== keepId), on);
    } else {
      onToggle(item, on);
    }
    anchor.current = index;
  };

  return (
    <ul className="grid">
      {page.items.map((item, index) => {
        const isSelected = selected.has(item.id);
        const otherPlace = place != null && placeOf(item.status) !== place;
        return (
          <li key={item.id} data-page={pageOfShown?.[index]} data-id={item.id} className={`card ${isSelected ? "selected" : ""} ${openId === item.id ? "open" : ""} ${item.id === keepId ? "card-keep" : ""}`}>
            <div className="card-preview">
              <button className="card-image" onClick={() => onOpen(item.id)} aria-label={`Open ${item.filename}`}>
                <Thumb refreshKey={refreshKey} id={item.id} alt={item.filename} />
              </button>
              {matchThreshold != null && item.similar_count != null && <span className="card-match-count" title={`${plural(item.similar_count, "match", "matches")} at or above ${matchThreshold}%`}>
                {plural(item.similar_count, "match", "matches")}
              </span>}
            </div>
            {item.id === keepId ? (
              <span className="card-keeping"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12" /></svg>Keeping</span>
            ) : (
            <label className="card-check" title={!selectable ? "Selection is unavailable while a job is running."
              : otherPlace ? (place === "library" ? "Photos in Rejects can't be selected with library photos. Clear the selection first."
                : "Library photos can't be selected with photos in Rejects. Clear the selection first.") : undefined}>
              <input
                type="checkbox"
                checked={isSelected}
                disabled={!selectable || otherPlace}
                onChange={() => undefined}
                onClick={(e) => toggle(index, e.shiftKey)}
                aria-label={`Select ${item.filename}`}
              />
            </label>
            )}
            <div className="card-meta">
              <span className="card-name" title={item.filename}>{item.filename}</span>
              <span className="card-sub">
                <span title={isFallbackDate(item.date_source) ? "No capture date: this is the file's modification date" : undefined}>
                  {photoDate(item.date_taken, false)}
                  {isFallbackDate(item.date_source) ? " (file date)" : ""}
                </span>
                {item.kept ? (
                  <span className="badge badge-copied_only"
                        title={`A Move copied this photo but could not remove the original: ${item.kept}. Moving it again once the source can be written finishes the Move.`}>
                    Copied only
                  </span>
                ) : STATUS_BADGE[item.status] && (
                  <span className={`badge badge-${item.status.toLowerCase()}`}
                        title={item.failure ? `Failed: ${item.failure}`
                          : item.rejected_at ? `Rejected ${epoch(Date.parse(item.rejected_at) / 1000)}${item.status === "Rejected_Copied" ? "; its source is still in place, and a Move removes it" : ""}`
                          : undefined}>{STATUS_BADGE[item.status]}</span>
                )}
                {item.duplicates > 0 && <span className="badge">{plural(item.duplicates, "duplicate")}</span>}
              </span>
            </div>
            {onExploreSet && <div className="set-card-actions">
              <strong>Reference set · {plural((item.similar_count ?? 0) + 1, "photo")}</strong>
              <span className="section-note">Identical sets shown once. Explore members and related sets.</span>
              <button onClick={() => onReviewSet?.(item.id)}>Review this set</button>
              <button onClick={() => onExploreSet(item.id)}>Explore related sets</button>
            </div>}
          </li>
        );
      })}
    </ul>
  );
}
