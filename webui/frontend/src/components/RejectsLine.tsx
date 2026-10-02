import { useId, useState } from "react";
import type { PhotoPage, Status } from "../api";
import { bytes, day, plural } from "../format";
import { follow } from "../nav";

// How to empty Rejects: the application never deletes a photo, so emptying is the user's,
// done on the host. The guidance is essential, so it stays in the page rather than in a hover.
function useEmptyHelp() {
  const [open, setOpen] = useState(false);
  const id = useId();
  const toggle = (
    <button className="link" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
      How to empty Rejects
    </button>
  );
  const help = (
    <p id={id} className="muted" hidden={!open}>
      Delete the files in the rejects folder of your destination, in your file manager. NegativeSpace never
      deletes photos itself; they leave Rejects as soon as they are gone.
    </p>
  );
  return { toggle, help };
}

// What Rejects holds, above the Rejects view (webui-spec 7.8).
export function RejectsLine({ rejects }: { rejects: NonNullable<PhotoPage["rejects"]> }) {
  const { toggle, help } = useEmptyHelp();
  return (
    <div className="dates-filter-line rejects-line">
      <p>
        {rejects.photos === 0 ? "Rejects is empty." : <>
          Rejects holds {plural(rejects.photos, "photo")} · {bytes(rejects.bytes)}
          {rejects.oldest_rejected_at && <> · oldest rejected {day(rejects.oldest_rejected_at)}</>}
        </>}
        {" "}{toggle}
      </p>
      {help}
    </div>
  );
}

// On every page while Rejects is past its size or age limit (Settings). No Dismiss: it
// goes once Rejects is under both limits again.
export function RejectsReminder({ status, inRejectsView = false }: { status: Status; inRejectsView?: boolean }) {
  const { toggle, help } = useEmptyHelp();
  const r = status.rejects;
  if (!r || r.photos === 0 || !(r.reminder.over_size || r.reminder.over_age)) return null;
  const old = `photos rejected more than ${plural(r.reminder.days_limit ?? 0, "day")} ago`;
  const text = r.reminder.over_size && r.reminder.over_age ? `Rejects holds ${bytes(r.bytes)}, including ${old}`
    : r.reminder.over_size ? `Rejects holds ${bytes(r.bytes)} in ${plural(r.photos, "photo")}`
    : `Rejects holds ${old} (${plural(r.photos, "photo")} · ${bytes(r.bytes)})`;
  return (
    <div className="rejects-reminder" role="region" aria-label="Rejects reminder">
      <p>
        {text} · {toggle}
        {!inRejectsView && <> · <a href="/?view=rejects" onClick={follow}>Open Rejects</a></>}
      </p>
      {help}
    </div>
  );
}
