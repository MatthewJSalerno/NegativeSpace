import type { ReactNode } from "react";
import { LABELS, own, stable, comparable, display } from "./metadataFields";

export function MetadataFieldTable({ caption, fields, source, primary, primaryLabel = "Primary value", sourceLabel, extra }: {
  caption:string; fields:string[]; source:Record<string,unknown>; primary?:Record<string,unknown>;
  primaryLabel?:string; sourceLabel?:string; extra?:(field:string)=>ReactNode;
}) {
  const differs=(key:string)=>primary !== undefined && (own(source,key)!==own(primary,key)
    || stable(comparable(source[key],key))!==stable(comparable(primary[key],key)));
  return <table className="review-metadata-table"><caption>{caption}</caption>
    <thead><tr><th scope="col">Field</th>{primary !== undefined && <th scope="col">{primaryLabel}</th>}
      <th scope="col">{sourceLabel ?? (primary !== undefined ? "This source" : "Value")}</th></tr></thead>
    <tbody>{fields.map(key=><tr key={key} data-different={differs(key)}>
      <th scope="row">{LABELS[key] ?? key}{differs(key) && <small>Different</small>}</th>
      {primary !== undefined && <td>{display(primary,key)}</td>}
      <td>{display(source,key)}{extra?.(key)}</td>
    </tr>)}</tbody>
  </table>;
}
