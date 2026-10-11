import { useEffect, useRef, type ReactNode } from "react";

// The Filters button above the gallery (webui-spec 2): Types, then Folders or Dates, in a
// panel that opens under it, over the photos. A disclosure, not a dialog: the gallery
// updates behind it as boxes are ticked. Esc, Close or a click outside closes it; it
// stays mounted while closed, so the trees keep what is open in them.
export function FiltersButton({ active, open, onOpen, disabled, children }: {
  active: number;
  open: boolean;
  onOpen: (open: boolean) => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!root.current?.contains(e.target as Node)) onOpen(false); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open, onOpen]);
  const close = () => { onOpen(false); button.current?.focus(); };
  return (
    <div className="filters" ref={root}
         onKeyDown={(e) => { if (open && e.key === "Escape" && !e.defaultPrevented) { e.preventDefault(); close(); } }}>
      <button ref={button} type="button" className={active ? "active-soft" : undefined} aria-expanded={open}
              aria-controls="filters-panel" disabled={disabled} onClick={() => onOpen(!open)}>
        Filters{active ? ` (${active})` : ""} <span aria-hidden="true">▾</span>
      </button>
      <div id="filters-panel" className="filters-panel" role="region" aria-label="Filters" hidden={!open}>
        <div className="filters-panel-head">
          <h2>Filters</h2>
          <button type="button" className="icon" aria-label="Close filters" title="Close filters" onClick={close}>✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}
