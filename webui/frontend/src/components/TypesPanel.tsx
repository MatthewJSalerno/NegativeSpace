import { useState } from "react";
import { count } from "../format";

const OPEN_KEY = "ns.typesOpen";

// The Types section, above Dates and folded by default (webui-spec 2): the file types the
// library holds, as the view, search and dates narrow it, with "Show only" boxes. None
// checked shows every type. Folded, it still names any type checked, so an active filter
// is never hidden; a filter in the address opens it. Open or folded is remembered per
// browser. A checked type stays listed at 0, so it can always be unchecked.
export function TypesPanel({ types, selected, onTypes }: {
  types: { type: string; photos: number }[] | null;
  selected: string[];
  onTypes: (types: string[]) => void;
}) {
  const [open, setOpenState] = useState(() => {
    if (selected.length) return true;
    try { return localStorage.getItem(OPEN_KEY) === "1"; } catch { return false; }
  });
  const setOpen = (next: boolean) => {
    setOpenState(next);
    try { localStorage.setItem(OPEN_KEY, next ? "1" : "0"); } catch { /* a convenience only */ }
  };
  if (!types) return null;
  const rows = [...types, ...selected.filter((t) => !types.some((x) => x.type === t)).map((t) => ({ type: t, photos: 0 }))];
  if (rows.length === 0) return null;
  const toggle = (t: string) => onTypes(selected.includes(t) ? selected.filter((x) => x !== t) : [...selected, t]);
  return (
    <nav className="types-panel" aria-label="Types">
      <div className="dates-head">
        <h2>
          <button className="types-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
            <span aria-hidden="true">{open ? "▾" : "▸"}</span> Types
            {!open && selected.length > 0 && <span className="types-active"> · {selected.map(typeLabel).join(", ")}</span>}
          </button>
        </h2>
        {open && (
          <span className="dates-show-only" title="Check file types to show only those. Uncheck them all to show every type.">
            Show only <span aria-hidden="true">ⓘ</span>
          </span>
        )}
      </div>
      {open && <>
      <ul className="dates-tree">
        {rows.map((r) => (
          <li key={r.type} className="dates-row month type-row">
            <input type="checkbox" id={`type-${r.type}`} checked={selected.includes(r.type)} onChange={() => toggle(r.type)}
                   aria-label={`Show only ${typeLabel(r.type)}`} />
            <label htmlFor={`type-${r.type}`} className="dates-name">{typeLabel(r.type)}</label>
            <span className="dates-count">{count(r.photos)}</span>
          </li>
        ))}
      </ul>
      <p className="dates-foot muted">
        {selected.length === 0 ? "Showing every type" : <>Showing only {selected.map(typeLabel).join(", ")} · <button className="link" onClick={() => onTypes([])}>Show all</button></>}
      </p>
      </>}
    </nav>
  );
}

export function typeLabel(t: string): string {
  return t ? t.toUpperCase() : "No extension";
}
