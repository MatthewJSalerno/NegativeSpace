import { useRef } from "react";
import type { PhotoItem } from "../api";
import { isFallbackDate, photoDate, plural } from "../format";
import { Thumb } from "./Thumb";

const STATUS_BADGE: Record<string, string> = {
  Completed: "Moved", Copied: "Copied", Found_At_Destination: "At destination", Failed: "Failed",
  Processing: "In progress",
};

export function Gallery({ page, pageOf, selected, selectable, openId, onOpen, onToggle, onToggleMany }: {
  page: { items: PhotoItem[] };
  // The page each photo came from, so scrolling can tell which page is on top.
  pageOf?: number[];
  selected: Set<number>;
  selectable: boolean;
  openId: number | null;
  onOpen: (id: number) => void;
  onToggle: (item: PhotoItem, on: boolean) => void;
  onToggleMany: (items: PhotoItem[], on: boolean) => void;
}) {
  const anchor = useRef<number | null>(null);

  // Shift-click selects the range from the last photo clicked, on this page.
  const toggle = (index: number, shift: boolean) => {
    const item = page.items[index];
    const on = !selected.has(item.id);
    if (shift && anchor.current != null) {
      const [a, b] = [anchor.current, index].sort((x, y) => x - y);
      onToggleMany(page.items.slice(a, b + 1), on);
    } else {
      onToggle(item, on);
    }
    anchor.current = index;
  };

  return (
    <ul className="grid">
      {page.items.map((item, index) => {
        const isSelected = selected.has(item.id);
        return (
          <li key={item.id} data-page={pageOf?.[index]} data-id={item.id} className={`card ${isSelected ? "selected" : ""} ${openId === item.id ? "open" : ""}`}>
            <button className="card-image" onClick={() => onOpen(item.id)} aria-label={`Open ${item.filename}`}>
              <Thumb id={item.id} alt={item.filename} />
            </button>
            <label className="card-check" title={selectable ? undefined : "Selection is unavailable while a job is running."}>
              <input
                type="checkbox"
                checked={isSelected}
                disabled={!selectable}
                onChange={() => undefined}
                onClick={(e) => toggle(index, e.shiftKey)}
                aria-label={`Select ${item.filename}`}
              />
            </label>
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
                        title={item.failure ? `Failed: ${item.failure}` : undefined}>{STATUS_BADGE[item.status]}</span>
                )}
                {item.duplicates > 0 && <span className="badge">{plural(item.duplicates, "duplicate")}</span>}
              </span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
