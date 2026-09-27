import type { Ref } from "react";

export function PageBoundary({ ref, error, pending, previous = false, onLoad }: {
  ref?: Ref<HTMLDivElement>; error?: string; pending: boolean; previous?: boolean; onLoad: () => void;
}) {
  const label = previous ? "Load previous photos" : "Load more photos";
  return <div ref={ref} className="page-sentinel">
    {error && <p className="error" role="alert">Photos could not be loaded. {error}</p>}
    <span role="status">{pending ? "Loading more photos…" : ""}</span>
    <button disabled={pending} onClick={onLoad}>{error ? `Retry: ${label.toLowerCase()}` : label}</button>
  </div>;
}
