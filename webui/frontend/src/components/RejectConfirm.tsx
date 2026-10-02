import { useState } from "react";
import { Modal } from "./ui/Modal";

// The question before a reject in the comparison (webui-spec 7.8): one sentence, Cancel
// first. "Don't ask again while comparing" lasts until the comparison closes. A reject
// that would leave none of the compared photos in the library always asks, and says so.
export function RejectConfirm({ filename, last, rejectedHere, offerDontAsk, onCancel, onConfirm }: {
  filename: string;
  last: boolean;
  rejectedHere: number;
  offerDontAsk: boolean;
  onCancel: () => void;
  onConfirm: (dontAskAgain: boolean) => void;
}) {
  const [dontAsk, setDontAsk] = useState(false);
  return (
    <Modal role="alertdialog" labelledBy="reject-confirm-title" onClose={onCancel}>
      <h2 id="reject-confirm-title">{last ? `Reject ${filename} too?` : `Reject ${filename}?`}</h2>
      {last && <p className="reject-last">
        <strong>None of these photos would be left in the library.</strong>
        {rejectedHere > 0 ? ` You have rejected ${rejectedHere === 1 ? "its look-alike" : `its ${rejectedHere} look-alikes`} in this comparison; this is the last one.` : ""}
      </p>}
      <p>It moves to the Rejects folder and leaves your library. You can bring it back any time until you manually empty Rejects.</p>
      {offerDontAsk && !last && <label className="checkbox-row">
        <input type="checkbox" checked={dontAsk} onChange={(e) => setDontAsk(e.target.checked)} />
        Don't ask again while comparing
      </label>}
      <footer className="settings-actions">
        <button data-initial-focus onClick={onCancel}>Cancel</button>
        <button className="primary" onClick={() => onConfirm(dontAsk)}>{last ? "Reject it too" : "Reject"}</button>
      </footer>
    </Modal>
  );
}
