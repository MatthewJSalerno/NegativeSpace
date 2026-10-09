import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import type { PlaceView, Status } from "../api";
import { follow, useHeaderHeight } from "../nav";
import { Logo } from "./Logo";
import { PageTools } from "./PageTools";
import { Sidebar, type SidebarCurrent, type SidebarFilters } from "./Sidebar";

// The page frame (webui-spec 2; ui-design.md "Page frame"), shared by Library, Logs and
// Stats: the sticky top bar, with the page's banners under it, then the navigation
// sidebar beside the page. While photos are selected the selection bar takes the whole
// top bar. Below 800px the sidebar hides behind the menu button and opens over the page;
// the button stays while photos are selected, so the places and filters are still in reach.
export function AppFrame({ header, current, status, onOpenSettings, search, jobs, selection, banners,
                           matchMin, refresh, filters, onPlace, className = "", children }: {
  header: RefObject<HTMLElement | null>;
  current: SidebarCurrent;
  status: Status;
  onOpenSettings: () => void;
  search?: ReactNode;
  jobs?: ReactNode;
  selection?: ReactNode;
  banners?: ReactNode;
  matchMin?: number;
  refresh?: unknown;
  filters?: SidebarFilters;
  onPlace?: (view: PlaceView) => void;
  className?: string;
  children: ReactNode;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);
  useHeaderHeight(header);
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      setMenuOpen(false);
      toggle.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);
  return (
    <div className={`app ${className} ${menuOpen ? "menu-open" : ""}`}>
      <header className="toolbar" ref={header}>
        <div className={`topbar ${selection ? "selecting" : ""}`}>
          <button ref={toggle} type="button" className="icon menu-toggle" aria-label="Menu" aria-expanded={menuOpen}
                  aria-controls="sidebar" onClick={() => setMenuOpen(!menuOpen)}><span aria-hidden="true">☰</span></button>
          {selection ?? <>
            <h1 className="brand"><a href="/" onClick={follow}><Logo />NegativeSpace</a></h1>
            <div className="topbar-search">{search}</div>
            {jobs}
            <PageTools onOpenSettings={onOpenSettings} />
          </>}
        </div>
        {banners}
      </header>
      <div className="frame-body">
        {menuOpen && <div className="sidebar-backdrop" onClick={() => setMenuOpen(false)} />}
        <Sidebar current={current} version={status.version} matchMin={matchMin} refresh={refresh ?? status}
                 filters={filters} onPlace={onPlace} onNavigate={() => setMenuOpen(false)} />
        {children}
      </div>
    </div>
  );
}
