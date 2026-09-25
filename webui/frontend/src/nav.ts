// Moving between the app's pages without reloading: the Library at "/" and the log
// at "/logs". The address bar stays the source of truth, so a refresh, a bookmark
// or the back button lands in the same place.
import { useEffect, useState, type MouseEvent } from "react";

export function navigate(url: string) {
  window.history.pushState(null, "", url);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function usePath(): string {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  return path;
}

// For <a href> links: a plain click navigates in place; a middle or ctrl-click still
// opens a new tab.
export function follow(e: MouseEvent<HTMLAnchorElement>) {
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  navigate(e.currentTarget.getAttribute("href") ?? "/");
}

export function logUrl(filters: { run?: number | null; status?: string; photo?: number }): string {
  const p = new URLSearchParams();
  if (filters.run != null) p.set("run", String(filters.run));
  if (filters.status) p.set("status", filters.status);
  if (filters.photo != null) p.set("photo", String(filters.photo));
  return `/logs${p.size ? `?${p}` : ""}`;
}
