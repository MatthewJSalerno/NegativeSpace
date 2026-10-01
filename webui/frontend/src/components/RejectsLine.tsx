import { useId, useState } from "react";
import type { PhotoPage } from "../api";
import { bytes, day, plural } from "../format";

// What Rejects holds, above the Rejects view (webui-spec 7.8), and how to empty it: the
// application never deletes a photo, so emptying is the user's, done on the host. The
// guidance is essential, so it stays in the page rather than in a hover.
export function RejectsLine({ rejects }: { rejects: NonNullable<PhotoPage["rejects"]> }) {
  const [open, setOpen] = useState(false);
  const help = useId();
  return (
    <div className="dates-filter-line rejects-line">
      <p>
        {rejects.photos === 0 ? "Rejects is empty." : <>
          Rejects holds {plural(rejects.photos, "photo")} · {bytes(rejects.bytes)}
          {rejects.oldest_rejected_at && <> · oldest rejected {day(rejects.oldest_rejected_at)}</>}
        </>}
        {" "}<button className="link" aria-expanded={open} aria-controls={help} onClick={() => setOpen(!open)}>
          How to empty Rejects
        </button>
      </p>
      <p id={help} className="muted" hidden={!open}>
        Delete the files in the rejects folder of your destination, in your file manager. NegativeSpace never
        deletes photos itself; they leave this view as soon as they are gone.
      </p>
    </div>
  );
}
