import { useEffect, useRef, useState } from "react";
import { count } from "../format";

// Selecting in bulk (webui-spec 2): the photos on screen, or everything the view shows,
// and the same two to unselect. An item that would do nothing, or cannot, says why.
export function SelectMenu({ onScreen, screenSelected, total, selected, max, disabledWhy, onSelectScreen, onSelectAll,
                             onUnselectScreen, onUnselectAll }: {
  onScreen: number;
  screenSelected: number;
  total: number;
  selected: number;
  max: number;
  disabledWhy: string | null;
  onSelectScreen: () => void;
  onSelectAll: () => void;
  onUnselectScreen: () => void;
  onUnselectAll: () => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => root.current && !root.current.contains(e.target as Node) && setOpen(false);
    const key = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", key); };
  }, [open]);

  const run = (fn: () => void) => () => { setOpen(false); fn(); };
  const items = [
    { label: `Select all on screen (${count(onScreen)})`, onClick: onSelectScreen,
      why: disabledWhy ?? (screenSelected === onScreen ? "Every photo on screen is selected." : null),
      hint: "The photos you can see right now." },
    { label: `Select all in this view (${count(total)})`, onClick: onSelectAll,
      why: disabledWhy ?? (total > max
        ? `More than the ${count(max)}-photo limit. Use Actions for all photos, or narrow the view.` : null),
      hint: "Every photo the view, search and dates show, scrolled to or not." },
    { label: "Unselect all on screen", onClick: onUnselectScreen,
      why: disabledWhy ?? (screenSelected === 0 ? "Nothing on screen is selected." : null) },
    { label: "Unselect all", onClick: onUnselectAll, why: selected === 0 ? "Nothing is selected." : null },
  ];

  return (
    <div className="actions-menu select-menu" ref={root}>
      <button className={open ? "active-soft" : ""} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        Select <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="menu" role="menu" aria-label="Select">
          {items.map((item) => (
            <button key={item.label} role="menuitem" className="menu-item" disabled={item.why != null}
                    onClick={run(item.onClick)}>
              <span className="menu-label">{item.label}</span>
              {(item.why ?? item.hint) && <span className="menu-hint">{item.why ?? item.hint}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
