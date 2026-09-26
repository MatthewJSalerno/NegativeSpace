import { count } from "../format";

// The Types section, under Dates (webui-spec 2): the file types the library holds, as
// the view, search and dates narrow it, with "Show only" boxes. None checked shows every
// type. A checked type stays listed at 0, so it can always be unchecked.
export function TypesPanel({ types, selected, onTypes }: {
  types: { type: string; photos: number }[] | null;
  selected: string[];
  onTypes: (types: string[]) => void;
}) {
  if (!types) return null;
  const rows = [...types, ...selected.filter((t) => !types.some((x) => x.type === t)).map((t) => ({ type: t, photos: 0 }))];
  if (rows.length === 0) return null;
  const toggle = (t: string) => onTypes(selected.includes(t) ? selected.filter((x) => x !== t) : [...selected, t]);
  return (
    <nav className="types-panel" aria-label="Types">
      <div className="dates-head">
        <h2>Types</h2>
        <span className="dates-show-only" title="Check file types to show only those. Uncheck them all to show every type.">
          Show only <span aria-hidden="true">ⓘ</span>
        </span>
      </div>
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
    </nav>
  );
}

export function typeLabel(t: string): string {
  return t ? t.toUpperCase() : "No extension";
}
