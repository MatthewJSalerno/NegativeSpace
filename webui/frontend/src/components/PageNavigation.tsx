import type { ReactNode } from "react";
import { follow } from "../nav";

// Keep navigation landmarks in the same slots when context-specific Jobs is absent.
export function PageNavigation({ active, jobs }: { active?: "library" | "logs"; jobs?: ReactNode }) {
  return <nav className="pages" aria-label="Pages">
    <a className={`button-link${active === "library" ? " active" : ""}`} href="/" onClick={follow}
      aria-current={active === "library" ? "page" : undefined}>Library</a>
    <div className="page-jobs-slot" aria-hidden={!jobs || undefined}>{jobs}</div>
    <a className={`button-link${active === "logs" ? " active" : ""}`} href="/logs" onClick={follow}
      aria-current={active === "logs" ? "page" : undefined}>Logs</a>
  </nav>;
}
