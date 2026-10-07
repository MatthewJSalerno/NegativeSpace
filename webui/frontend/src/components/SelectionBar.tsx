import type { ActionMode, Place } from "../api";
import { count, plural } from "../format";

export type SelectionCounts = Record<ActionMode, number>;

// The selection bar (webui-spec 4): the ticked photos and the actions that apply to them,
// in the sticky top bar while anything is selected. An action that cannot take any of the
// selected photos is left out rather than shown disabled; each still asks first, through
// the same review as before. While a job runs the actions wait, saying why. A selection
// in Rejects offers Return to library first, and its Move says what it deletes.
export function SelectionBar({ selected, outside, focused, reviewing, counts, place, jobRunning, onAction, onShowSelected,
                               onBack, onClear }: {
  selected: number;
  outside: number;
  focused: boolean;
  reviewing: boolean;
  counts: SelectionCounts;
  place: Place | null;
  jobRunning: boolean;
  onAction: (mode: ActionMode) => void;
  onShowSelected: () => void;
  onBack: () => void;
  onClear: () => void;
}) {
  const copy = { mode: "copy" as const, label: "Copy", hint: "Copy the selected photos not yet copied. The source is left untouched." };
  const reject = { mode: "reject" as const, label: "Reject", hint: "Move the selected photos out of the library into Rejects. Nothing is deleted." };
  const back = { mode: "return" as const, label: "Return to library", hint: "Move the selected photos from Rejects back to their date folders." };
  const actions: { mode: ActionMode; label: string; hint: string }[] = place === "rejects" ? [
    back,
    { mode: "move", label: "Move", hint: "Delete the originals of these rejected photos from the source, once each copy in Rejects is verified. Those copies become the only ones." },
  ] : [
    copy,
    { mode: "move", label: "Move", hint: "Move the selected photos; each source is deleted once its copy is verified." },
    reject,
  ];
  const offered = reviewing ? [] : actions.filter((a) => counts[a.mode] > 0);
  const busy = jobRunning ? "A job is running. Wait for it to finish or cancel it." : undefined;
  return (
    <div className="selection-line" role="region" aria-label="Selection">
      <span className="selection-summary">
        <strong>{plural(selected, "photo")} selected</strong>
        {!focused && <span className="muted selection-outside">
          <span className="selection-outside-size" aria-hidden="true">{count(selected)} outside this view</span>
          <span>{outside > 0 ? `${count(outside)} outside this view` : ""}</span>
        </span>}
      </span>
      {offered.length > 0 && (
        <span className="selection-actions">
          {offered.map((a) => (
            <button key={a.mode} type="button" className="photo-action" disabled={jobRunning} title={busy ?? a.hint}
                    onClick={() => onAction(a.mode)}>
              {a.label} ({count(counts[a.mode])})…
            </button>
          ))}
        </span>
      )}
      {focused
        ? <button className="link" onClick={onBack}>Back to results</button>
        : selected > 0 && <button className="link" onClick={onShowSelected}>Show only selected</button>}
      {selected > 0 && <button className="link" onClick={onClear}>Clear</button>}
    </div>
  );
}
