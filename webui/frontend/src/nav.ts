// Moving between the app's pages without reloading: the Library at "/" and the log
// at "/logs". The address bar stays the source of truth, so a refresh, a bookmark
// or the back button lands in the same place.
import { useEffect, useState, type MouseEvent, type RefObject } from "react";

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

// The sticky header's height, for everything that sticks below it: it grows when the
// finished-job banner shows or the toolbar wraps on a narrow screen.
export function useHeaderHeight(header: RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!header.current) return;
    const observer = new ResizeObserver(([entry]) =>
      document.documentElement.style.setProperty("--header-h", `${Math.ceil(entry.target.getBoundingClientRect().height)}px`));
    observer.observe(header.current);
    return () => observer.disconnect();
  }, [header]);
}
