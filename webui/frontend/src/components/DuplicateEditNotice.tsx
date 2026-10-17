import type { EditDuplicate } from "../api";

export function DuplicateEditNotice({ duplicate }: { duplicate: EditDuplicate }) {
  return <div className="notice" role="status">
    <p>This edit would make an identical copy of <strong>{duplicate.filename}</strong>.</p>
    <p>Keep the existing photo at <code>{duplicate.path}</code> and remove this edited copy after verification. Both histories and recorded XMP versions are preserved. Source files stay untouched.</p>
  </div>;
}
