import type { ReactNode } from "react";

// Shared by information panes, recovery dialogs and operation details. Labels and
// a divider distinguish origin from output without relying on color or an arrow.
export function FileLocations({ source = [], destination = [], destinationLabel = "Destination" }: {
  source?: { label: string; path: string; note?: ReactNode; status?: { text: string; tone: "ok" | "warning" | "error" } }[];
  destination?: { label: string; path: string; note?: ReactNode; status?: { text: string; tone: "ok" | "warning" | "error" } }[];
  destinationLabel?: string;
}) {
  return <div className="file-locations">
    {[{label: "Source", files: source}, {label: destinationLabel, files: destination}].filter(g=>g.files.length).map(group=>
      <div className="file-location-group" key={group.label} role="group" aria-label={group.label}>
        <strong>{group.label}</strong>
        <dl>{group.files.map((file,i)=><div key={i} className="file-location-entry">
          <dt>{file.label}</dt>
          <dd>{file.status && <div className={file.status.tone}><strong>{file.status.text}</strong></div>}<code className={file.status?.tone}>{file.path}</code>{file.note && <div className="muted">{file.note}</div>}</dd>
        </div>)}</dl>
      </div>)}
  </div>;
}
