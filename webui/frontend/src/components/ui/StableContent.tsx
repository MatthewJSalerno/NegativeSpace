import type { ReactNode } from "react";

// Known guidance variants share a grid cell. The largest reserves the space at
// the current width/text size; hidden variants cannot be read, clicked or focused.
export function StableContent({ active, variants, className = "", id }: {
  active: string; variants: Record<string, ReactNode>; className?: string; id?: string;
}) {
  return <div id={id} className={`stable-content ${className}`}>
    {Object.entries(variants).map(([key, content]) => <div key={key}
      aria-hidden={key !== active} inert={key !== active}>{content}</div>)}
  </div>;
}
