import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { api, ApiError, type PhotoItem, type PhotoPage, type SelectionPage, type Sort, type Status, type Timeline, type View } from "./api";
import { count, plural } from "./format";
import { useDismissedRun, useJobFeed } from "./jobs";
import { Gallery } from "./components/Gallery";
import { Inspector } from "./components/Inspector";
import { FinishedBanner, JobDrawer } from "./components/JobDrawer";
import { PAGE_SIZES, Pager } from "./components/Pager";
import { DatesPanel, dateLabel, datePage } from "./components/DatesPanel";
import { SelectMenu } from "./components/SelectMenu";
import { usePaged } from "./paged";
import { ConfirmDialog, transferConfirm, type Confirm } from "./components/Confirm";
import { Tip } from "./components/Tip";
import { ActionsMenu } from "./components/ActionsMenu";
import { LogsPage } from "./components/LogsPage";
import { follow, navigate, useHeaderHeight, usePath } from "./nav";
import { SettingsDialog } from "./components/SettingsDialog";

// Neither side of the gallery/Inspector divider gets narrower than this.
const MIN_SIDE = 320;
const MAX_SELECTION = 1000; // mirrors the API's --file-ids limit (webui-spec 2)
const VIEW_LABEL: Record<View, string> = { all: "All photos", unorganized: "Not yet organized", organized: "Organized" };

// Browsing state lives in the URL, so a refresh or a shared link keeps the place.
function readUrl() {
  const p = new URLSearchParams(window.location.search);
  const view = (p.get("view") as View) || "all";
  return {
    view: (["all", "unorganized", "organized"] as View[]).includes(view) ? view : "all",
    sort: (p.get("sort") as Sort) || "newest",
    q: p.get("q") || "",
    page: Math.max(1, Number(p.get("page")) || 1),
    size: PAGE_SIZES.includes(Number(p.get("size"))) ? Number(p.get("size")) : PAGE_SIZES[0],
    undated: p.get("undated") === "1",
    dates: p.getAll("date"),
    photo: p.get("photo") ? Number(p.get("photo")) : null,
  };
}


// Showing only a set of photos, whatever the view, search and dates would hide: the
// selection (Show only selected), or the photos a job just started on. `ids` is fixed
// on entry, so unticking a photo there leaves it on screen, unticked.
// "review" is the selection before a Copy or Move of it: shown in full, with the action
// in a bar above it, so every photo can be looked at and unticked before committing.
type Focus = { kind: "selection" | "review" | "job"; ids: number[]; mode?: "copy" | "move" };

export function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [firstRunDone, setFirstRunDone] = useState(false);
  const path = usePath();

  const loadStatus = useCallback(() =>
    api.status().then((s) => { setStatus(s); setStatusError(null); },
                      () => setStatusError("The NegativeSpace server is not answering. Check that the container is running.")), []);
  useEffect(() => { loadStatus(); }, [loadStatus]);

  if (statusError) return <div className="center-page"><p className="error">{statusError}</p></div>;
  if (!status) return <div className="center-page muted">Loading…</div>;
  if (status.state === "missing") return <FirstRun status={status} onCreated={loadStatus} />;
  if (status.state !== "ok") return <CatalogProblem status={status} />;
  // First run: nothing indexed yet, so settings are the destination (webui-spec 3).
  if (!status.indexed && !firstRunDone) {
    // Saved, the user lands in the Library, where Index your library waits: never on the
    // page an earlier session left in the address bar.
    return <div className="center-page"><SettingsDialog firstRun onClose={() => undefined}
                                                        onSaved={() => { navigate("/"); setFirstRunDone(true); }} /></div>;
  }
  return (
    <>
      {path === "/logs"
        ? <LogsPage status={status} refreshStatus={loadStatus} onOpenSettings={() => setSettingsOpen(true)} />
        : <Library status={status} refreshStatus={loadStatus} onOpenSettings={() => setSettingsOpen(true)} />}
      {settingsOpen && <SettingsDialog firstRun={false} onClose={() => setSettingsOpen(false)} onSaved={() => undefined} />}
    </>
  );
}

function FirstRun({ status, onCreated }: { status: Status; onCreated: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.createCatalog();
      onCreated();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The catalog could not be created.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="center-page">
      <div className="panel">
        <h1>NegativeSpace</h1>
        <p>
          No catalog found. If this is your first time using NegativeSpace, create a catalog to get started.
          If you've used it before, check your appdata mount or recover your catalog from a backup.
        </p>
        <p className="muted">Application data: <code>{status.application_data}</code> · Catalog backups: <code>{status.catalog_backups}</code> (container paths)</p>
        {error && <p className="error">{error}</p>}
        <button className="primary" onClick={create} disabled={busy}>{busy ? "Creating…" : "Create new catalog"}</button>
      </div>
    </div>
  );
}

function CatalogProblem({ status }: { status: Status }) {
  return (
    <div className="center-page">
      <div className="panel">
        <h1>{status.state === "incompatible" ? "This catalog cannot be opened" : "The catalog could not be read"}</h1>
        <p>{status.detail}</p>
        <p>
          Nothing was changed. {status.state === "incompatible"
            ? "It was made by a different version of NegativeSpace. Recover a compatible catalog from a backup, or point the appdata mount at another catalog."
            : "Check that the application data folder is mounted and readable by the container, and that its storage is connected."}
        </p>
        <p className="muted">Application data: <code>{status.application_data}</code> · Catalog backups: <code>{status.catalog_backups}</code> (container paths)</p>
      </div>
    </div>
  );
}

function Library({ status, refreshStatus, onOpenSettings }: {
  status: Status;
  refreshStatus: () => void;
  onOpenSettings: () => void;
}) {
  const initial = useRef(readUrl()).current;
  const [view, setView] = useState<View>(initial.view);
  const [sort, setSort] = useState<Sort>(initial.sort);
  const [q, setQ] = useState(initial.q);
  const [search, setSearch] = useState(initial.q);
  // `jump` is where loading starts (the pager, a date, a filter change); `page` is the
  // page at the top of the screen, which scrolling moves and the address records.
  const [jump, setJump] = useState({ page: initial.page, n: 0 });
  const [page, setVisiblePage] = useState(initial.page);
  const setPage = (p: number) => { setJump((j) => ({ page: p, n: j.n + 1 })); setVisiblePage(p); };
  const [pageSize, setPageSize] = useState(initial.size);
  const [undated, setUndated] = useState(initial.undated);
  const [dates, setDates] = useState<string[]>(initial.dates);
  const [openId, setOpenId] = useState<number | null>(initial.photo);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [jumpTimeline, setJumpTimeline] = useState<Timeline | null>(null);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [focusJump, setFocusJump] = useState({ page: 1, n: 0 });
  const [focusPage, setFocusVisible] = useState(1);
  const setFocusPage = (p: number) => { setFocusJump((j) => ({ page: p, n: j.n + 1 })); setFocusVisible(p); };
  // A notice names its fixes as buttons that apply them, not as instructions.
  const [notice, setNoticeState] = useState<{ text: string; actions: { label: string; run: () => void }[] } | null>(null);
  const setNotice = (text: string | null, actions: { label: string; run: () => void }[] = []) =>
    setNoticeState(text == null ? null : { text, actions });
  // A date to go to once the date filter that hid it has changed.
  const [pendingJump, setPendingJump] = useState<string | null>(null);
  // Every photo on screen, as the last scroll found them.
  const [onScreen, setOnScreen] = useState<number[]>([]);
  const [datesOpen, setDatesOpen] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [dismissedId, dismissRun] = useDismissedRun();
  const { jobs, connection } = useJobFeed();
  const jobRunning = jobs.active != null && jobs.active.presented_status !== "Interrupted";
  const header = useRef<HTMLElement>(null);
  const content = useRef<HTMLElement>(null);
  const [panelWidth, setPanelWidth] = useState<number | null>(() => {
    try { return Number(localStorage.getItem("ns.inspectorWidth")) || null; } catch { return null; }
  });

  useHeaderHeight(header);

  // A finished job changes the catalog: refresh the view and the counts. Keyed on
  // the last finished run rather than on seeing a job stop, because a job shorter
  // than one feed update is never seen running at all. The first value seen is the
  // baseline even when there is no finished run yet, so the very first job on a new
  // catalog still refreshes the view.
  const lastFinished = jobs.last && !jobRunning ? `${jobs.last.id}:${jobs.last.status}` : null;
  const seenFinished = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (seenFinished.current !== undefined && lastFinished != null && seenFinished.current !== lastFinished) {
      setRefreshKey((k) => k + 1);
      refreshStatus();
    }
    seenFinished.current = lastFinished;
  }, [lastFinished, refreshStatus]);

  // Only a changed search goes back to page 1; loading the page keeps the URL's page.
  useEffect(() => {
    const t = window.setTimeout(() => {
      if (search.trim() !== q) { setQ(search.trim()); setPage(1); }
    }, 300);
    return () => window.clearTimeout(t);
  }, [search, q]);

  useEffect(() => {
    const p = new URLSearchParams();
    if (view !== "all") p.set("view", view);
    if (sort !== "newest") p.set("sort", sort);
    if (q) p.set("q", q);
    if (page > 1) p.set("page", String(page));
    if (pageSize !== PAGE_SIZES[0]) p.set("size", String(pageSize));
    if (undated) p.set("undated", "1");
    dates.forEach((d) => p.append("date", d));
    if (openId != null) p.set("photo", String(openId));
    const url = `${window.location.pathname}${p.size ? `?${p}` : ""}`;
    window.history.replaceState(null, "", url);
  }, [view, sort, q, page, pageSize, undated, dates, openId]);

  const results = usePaged((p) => api.photos({ view, sort, q, page: p, page_size: pageSize, undated, dates }),
                           JSON.stringify([view, sort, q, undated, dates]), jump, pageSize, refreshKey, setLoadError);
  const data: PhotoPage | null = results.meta;

  // The tree's counts ignore its own filter, so an unticked month keeps its number;
  // jumping needs the filtered months, to land on the right page.
  useEffect(() => {
    let live = true;
    api.timeline({ view, q, undated }).then((t) => live && setTimeline(t), () => live && setTimeline(null));
    return () => { live = false; };
  }, [view, q, undated, refreshKey]);
  useEffect(() => {
    let live = true;
    if (dates.length === 0) { setJumpTimeline(null); return; }
    api.timeline({ view, q, undated, dates }).then((t) => live && setJumpTimeline(t), () => live && setJumpTimeline(null));
    return () => { live = false; };
  }, [view, q, undated, dates, refreshKey]);

  const focused = usePaged((p) => (focus ? api.selection(focus.ids, sort, p, pageSize)
                                          : Promise.resolve({ items: [], total: 0, page: p, page_size: pageSize, missing: [] } as SelectionPage)),
                           JSON.stringify([focus, sort]), focusJump, pageSize, refreshKey, setLoadError);
  const focusData: SelectionPage | null = focus ? focused.meta : null;

  // What the gallery shows: the results, or only the selection. Every loaded page in
  // order, each photo tagged with its page so scrolling can say which page is on top.
  const list = focus ? focused : results;
  const visible = focus ? focusPage : page;
  const flat = useMemo(() => {
    const items: PhotoItem[] = [];
    const pageOf: number[] = [];
    for (const p of [...list.pages.keys()].sort((a, b) => a - b)) {
      for (const item of list.pages.get(p) ?? []) { items.push(item); pageOf.push(p); }
    }
    return { items, pageOf };
  }, [list.pages]);
  // The photos on screen, for Select all on screen; until first measured, the page.
  const screenItems = useMemo(() => {
    const ids = new Set(onScreen);
    const found = flat.items.filter((i) => ids.has(i.id));
    return found.length ? found : list.pages.get(visible) ?? [];
  }, [flat, onScreen, list.pages, visible]);
  const pages = list.meta ? Math.max(1, Math.ceil(list.meta.total / pageSize)) : 1;
  // "Outside this view": selected photos not among the results loaded on screen.
  const loadedIds = useMemo(() => new Set([...results.pages.values()].flat().map((i) => i.id)), [results.pages]);
  const outside = [...selected].filter((id) => !loadedIds.has(id)).length;
  // Every month with a photo on screen, highlighted in the tree. Photos, not pages: a
  // month with a few photos rarely starts a page or a row, and was skipped.
  const currentDates = useMemo(() => {
    if (sort !== "newest" && sort !== "oldest") return [];
    const dateOf = new Map<number, string | null>();
    for (const items of results.pages.values()) for (const i of items) dateOf.set(i.id, i.date_taken);
    const ids = onScreen.length ? onScreen : (results.pages.get(page) ?? []).slice(0, 1).map((i) => i.id);
    return [...new Set(ids.map((id) => dateOf.get(id)?.slice(0, 7)).filter((m): m is string => !!m))];
  }, [results.pages, onScreen, page, sort]);

  // Continuous scrolling: load the next page as the end nears, and the previous one as
  // the start does, keeping the photos on screen where they are.
  const topSentinel = useRef<HTMLDivElement>(null);
  const bottomSentinel = useRef<HTMLDivElement>(null);
  const prepend = useRef<{ height: number; y: number } | null>(null);
  useEffect(() => {
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        if (entry.target === bottomSentinel.current) list.load(list.last + 1);
        if (entry.target === topSentinel.current && list.first > 1 && !prepend.current) {
          prepend.current = { height: document.documentElement.scrollHeight, y: window.scrollY };
          list.load(list.first - 1);
        }
      }
    }, { rootMargin: "800px 0px" });
    if (topSentinel.current) observer.observe(topSentinel.current);
    if (bottomSentinel.current) observer.observe(bottomSentinel.current);
    return () => observer.disconnect();
  }, [list.first, list.last, list.load, list.ready, focus]);
  useLayoutEffect(() => {
    const mark = prepend.current;
    if (!mark) return;
    prepend.current = null;
    window.scrollTo(0, mark.y + document.documentElement.scrollHeight - mark.height);
  }, [list.first]);
  // The page on top follows the scroll: the page of the first photo below the header.
  useEffect(() => {
    let frame = 0;
    const onScroll = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const top = header.current?.getBoundingClientRect().bottom ?? 0;
        const bottom = window.innerHeight;
        let first: HTMLElement | null = null;
        const seen: number[] = [];
        for (const card of document.querySelectorAll<HTMLElement>(".grid .card[data-page]")) {
          const box = card.getBoundingClientRect();
          if (box.bottom <= top + 4) continue;
          if (box.top >= bottom) break;
          first ??= card;
          seen.push(Number(card.dataset.id));
        }
        if (!first) return;
        const p = Number(first.dataset.page);
        if (focus) setFocusVisible(p); else setVisiblePage(p);
        setOnScreen(seen);
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => { window.removeEventListener("scroll", onScroll); window.removeEventListener("resize", onScroll); cancelAnimationFrame(frame); };
  }, [focus]);
  // Photos arriving change what is on screen without a scroll: measure again.
  useEffect(() => { window.dispatchEvent(new Event("resize")); }, [flat]);
  // A jump starts at the top of the page it lands on.
  useEffect(() => { if (jump.n > 0) window.scrollTo(0, 0); }, [jump.n]);
  useEffect(() => { if (focusJump.n > 0) window.scrollTo(0, 0); }, [focusJump.n]);

  const showSelected = () => { setFocus({ kind: "selection", ids: [...selected] }); setFocusPage(1); };
  const backToResults = () => { setFocus(null); setFocusPage(1); };
  // Clearing the selection leaves nothing to show only, so it returns to the results.
  const clearSelection = () => { setSelected(new Set()); if (focus?.kind === "selection" || focus?.kind === "review") backToResults(); };

  const changeDates = (next: string[]) => { setDates(next); setPage(1); };
  // All photos means every photo: it also clears No capture date, the dates and the
  // search. The other views keep them, to narrow within them.
  const narrowed = undated || dates.length > 0 || !!q;
  const chooseView = (v: View) => {
    setView(v);
    setPage(1);
    if (v === "all") { setUndated(false); setDates([]); setSearch(""); setQ(""); }
  };
  const jumpTo = (key: string) => {
    const newestFirst = sort !== "oldest";
    const target = datePage(jumpTimeline ?? timeline ?? { months: [], undated: 0 }, newestFirst, pageSize, key);
    if (target == null) {
      const then = (next: string[]) => () => { setNotice(null); changeDates(next); setPendingJump(key); };
      setNotice(`${dateLabel(key)} is outside the dates shown.`, [
        { label: `Show ${dateLabel(key)} too`, run: then([...dates, key]) },
        { label: "Show all dates", run: then([]) },
      ]);
      return;
    }
    if (sort !== "newest" && sort !== "oldest") {
      setSort("newest");
      setNotice("Sorted newest first, so the gallery can go to a date.");
    } else {
      setNotice(null);
    }
    setPage(target);
  };

  // Go to the date once the filtered months that include it have arrived.
  useEffect(() => {
    if (!pendingJump) return;
    const source = dates.length ? jumpTimeline : timeline;
    const has = (m: string) => m === pendingJump || m.startsWith(`${pendingJump}-`);
    if (source && (source.months.some((m) => has(m.month)) || (pendingJump === "none" && source.undated > 0))) {
      setPendingJump(null);
      jumpTo(pendingJump);
    }
  }, [pendingJump, jumpTimeline, timeline, dates]);

  const changePageSize = (size: number) => {
    // Keep the first photo on screen in view: land on the page that holds it.
    const first = (page - 1) * pageSize;
    setPageSize(size);
    setPage(Math.floor(first / size) + 1);
  };

  const toggleIds = (ids: number[], on: boolean) => setSelected((cur) => {
    const next = new Set(cur);
    for (const id of ids) { if (on) next.add(id); else next.delete(id); }
    return next;
  });
  const toggle = (item: PhotoItem, on: boolean) => toggleIds([item.id], on);
  const toggleMany = (items: PhotoItem[], on: boolean) => toggleIds(items.map((i) => i.id), on);
  const selectAll = async () => {
    if (focus) { toggleIds(focus.ids, true); return; }
    try {
      const got = await api.photoIds({ view, q, undated, dates });
      if (got.over_limit) {
        setNotice(`${count(got.total)} photos are shown: more than the ${count(got.limit)}-photo selection limit. Use Actions for all photos, or narrow the view.`);
        return;
      }
      toggleIds(got.ids, true);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "The photos could not be selected.");
    }
  };

  const step = useCallback((delta: number) => {
    if (openId == null) return;
    const index = flat.items.findIndex((i) => i.id === openId);
    const next = flat.items[index + delta];
    if (next) setOpenId(next.id);
  }, [flat, openId]);

  // The divider between the gallery and the Inspector: drag it, or focus it and use
  // the arrow keys. Each side keeps at least MIN_SIDE pixels; the width is remembered.
  const setWidth = (px: number) => {
    const total = content.current?.getBoundingClientRect().width ?? window.innerWidth;
    const clamped = Math.round(Math.min(Math.max(px, MIN_SIDE), total - MIN_SIDE));
    setPanelWidth(clamped);
    try { localStorage.setItem("ns.inspectorWidth", String(clamped)); } catch { /* per-viewer convenience only */ }
  };
  const drag = (e: ReactPointerEvent) => {
    e.preventDefault();
    const right = content.current?.getBoundingClientRect().right ?? window.innerWidth;
    const move = (ev: PointerEvent) => setWidth(right - ev.clientX);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.classList.remove("dragging");
    };
    document.body.classList.add("dragging");
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  const currentWidth = () => panelWidth ?? (content.current?.getBoundingClientRect().width ?? window.innerWidth) / 2;

  const start = (mode: "index" | "copy" | "move", fileIds?: number[]) => async () => {
    setActionError(null);
    try {
      await api.startJob(fileIds ? { mode, file_ids: fileIds } : { mode });
      if (fileIds) {
        setSelected(new Set());
        // Showing the selection: keep showing these photos, to watch them change.
        setFocus((cur) => (cur ? { kind: "job", ids: fileIds } : null));
      }
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "The job could not be started.");
    }
  };

  // Copy or Move selected first shows every selected photo, with the action in a bar
  // above them rather than a dialog over them: scroll, open and untick, then commit.
  const transferSelected = (mode: "copy" | "move") => {
    setFocus({ kind: "review", mode, ids: [...selected] });
    setFocusPage(1);
  };
  const reviewIds = focus?.kind === "review" ? focus.ids.filter((id) => selected.has(id)) : [];
  const review = focus?.kind === "review" && focus.mode ? transferConfirm(focus.mode, status, reviewIds, start(focus.mode, reviewIds)) : null;
  const [committing, setCommitting] = useState(false);
  const commit = async () => {
    if (!review) return;
    setCommitting(true);
    try { await review.run(); } finally { setCommitting(false); }
  };

  const askTransfer = (mode: "copy" | "move", ids?: number[], onCancel?: () => void) =>
    setConfirm(transferConfirm(mode, status, ids, start(mode, ids), onCancel));

  const noPhotos = status.photos === 0;
  const tooMany = selected.size > MAX_SELECTION;

  const screenSelected = screenItems.filter((i) => selected.has(i.id)).length;
  const onPager = focus ? setFocusPage : setPage;

  return (
    <div className={`app ${openId != null ? "with-inspector" : ""}`}>
      <header className="toolbar" ref={header}>
        <div className="toolbar-row">
          <h1 className="brand">NegativeSpace</h1>
          <nav className="pages" aria-label="Pages">
            <a className="button-link active" href="/" onClick={follow} aria-current="page">Library</a>
            <ActionsMenu
              state={{ jobRunning, noPhotos, selected: selected.size, tooMany, maxSelection: MAX_SELECTION,
                       eligible: status.eligible, copied: status.copied }}
              onIndex={start("index")}
              onTransfer={(mode, scope) => (scope === "selected" ? transferSelected(mode) : askTransfer(mode))} />
            <a className="button-link" href="/logs" onClick={follow}>Logs</a>
          </nav>
          {(selected.size > 0 || focus) && (
            <div className="selection-line" role="region" aria-label="Selection">
              <strong>{plural(selected.size, "photo")} selected</strong>
              {!focus && outside > 0 && <span> · {count(outside)} outside this view</span>}
              {tooMany && <span className="error"> · {count(MAX_SELECTION)} file limit for individual selection</span>}
              {focus
                ? <button className="link" onClick={backToResults}>Back to results</button>
                : <button className="link" onClick={showSelected}>Show only selected</button>}
              {selected.size > 0 && <button className="link" onClick={clearSelection}>Clear</button>}
            </div>
          )}
          <div className="toolbar-actions">
            <button className="icon" onClick={onOpenSettings} aria-label="Settings" title="Settings">⚙</button>
          </div>
        </div>
        <div className={`toolbar-row toolbar-browse ${focus ? "is-muted" : ""}`}>
          <button className="dates-toggle" aria-expanded={datesOpen} onClick={() => setDatesOpen(!datesOpen)}>
            Dates{dates.length ? ` (${dates.length})` : ""}
          </button>
          <nav className="views" aria-label="Views">
            {(Object.keys(VIEW_LABEL) as View[]).map((v) => (
              <button key={v} className={v === view && !(v === "all" && narrowed) ? "active" : ""} disabled={!!focus}
                      onClick={() => chooseView(v)}>
                <span>{VIEW_LABEL[v]}</span> <span className="view-count">{data ? `(${count(data.counts[v])})` : ""}</span>
              </button>
            ))}
            <Tip text="Photos whose EXIF has no date taken. They are filed under Undated, by their file's modification date.">
              <button className={`filter ${undated ? "active" : ""}`} aria-pressed={undated} disabled={!!focus}
                      onClick={() => { setUndated(!undated); setPage(1); }}>
                <span>No capture date</span> <span className="view-count">{data ? `(${count(data.counts.undated)})` : ""}</span>
              </button>
            </Tip>
          </nav>
          <input className="search" type="search" placeholder="Search filenames" value={search} disabled={!!focus}
                 onChange={(e) => setSearch(e.target.value)} aria-label="Search filenames" />
          <select value={sort} onChange={(e) => { setSort(e.target.value as Sort); setPage(1); setFocusPage(1); }} aria-label="Sort">
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
            <option value="largest">Largest first</option>
            <option value="smallest">Smallest first</option>
            <option value="name">Name</option>
          </select>
        </div>
        <JobDrawer jobs={jobs} connection={connection} />
        <FinishedBanner jobs={jobs} dismissedId={dismissedId} onDismiss={dismissRun} />
        {actionError && <p className="error banner" role="alert">{actionError} <button onClick={() => setActionError(null)}>Dismiss</button></p>}
      </header>

      <main className={`content ${datesOpen ? "dates-open" : ""}`} ref={content}>
        {!focus && (
          <DatesPanel timeline={timeline} dates={dates} current={currentDates} oldestFirst={sort === "oldest"} onDates={changeDates}
                      onJump={(key) => { jumpTo(key); setDatesOpen(false); }} />
        )}
        <div className="gallery-pane">
          {loadError && <p className="error">{loadError}</p>}
          {notice && (
            <p className="notice" role="status">
              {notice.text}
              {notice.actions.map((a) => <span key={a.label}> <button className="link" onClick={a.run}>{a.label}</button> ·</span>)}
              {" "}<button className="link" onClick={() => setNotice(null)}>Dismiss</button>
            </p>
          )}
          {focus && review && focus.mode && (
            <div className="focus-head review-bar" role="region" aria-label={`Review before ${focus.mode === "move" ? "moving" : "copying"}`}>
              <div className="review-text">
                <strong>Review the {plural(focus.ids.length, "selected photo")} below</strong>
                <span className="muted"> · untick any you do not want; {plural(reviewIds.length, "photo")} will be {focus.mode === "move" ? "moved" : "copied"}.</span>
                <p className="muted">{review.body[0]}</p>
              </div>
              <button className={review.danger ? "danger" : "primary"} onClick={commit}
                      disabled={committing || jobRunning || reviewIds.length === 0 || reviewIds.length > MAX_SELECTION}
                      title={reviewIds.length === 0 ? "Every photo is unticked." : jobRunning ? "A job is running." : undefined}>
                {focus.mode === "move" ? "Move" : "Copy"} these {plural(reviewIds.length, "photo")}
              </button>
              <button onClick={backToResults} disabled={committing}>Cancel</button>
            </div>
          )}
          {focus && !review && (
            <div className="focus-head">
              <strong>
                {focus.kind === "job" ? `The ${plural(focus.ids.length, "photo")} in the job just started`
                  : `Showing only the ${plural(focus.ids.length, "selected photo")}`}
              </strong>
              <span className="muted">
                {focus.kind === "job" ? " · their status updates when the job ends." : " · whatever the view, search or dates would hide."}
              </span>
              <button onClick={backToResults}>Back to results</button>
              {focusData && focusData.missing.length > 0 && (
                <p className="warning">
                  {plural(focusData.missing.length, "selected photo is", "selected photos are")} no longer in the catalog.{" "}
                  <button className="link" onClick={() => toggleIds(focusData.missing, false)}>Remove from the selection</button>
                </p>
              )}
            </div>
          )}
          {!focus && dates.length > 0 && (
            <p className="dates-filter-line">
              Showing only {dates.map(dateLabel).join(", ")}
              {data && data.total > 0 && (
                <> · <button className="link" onClick={selectAll} disabled={jobRunning || data.total > MAX_SELECTION}
                             title={data.total > MAX_SELECTION ? `More than the ${count(MAX_SELECTION)}-photo selection limit.`
                                    : jobRunning ? "Selection is unavailable while a job is running." : undefined}>
                  Select these {count(data.total)}
                </button></>
              )}
              {" · "}<button className="link" onClick={() => changeDates([])}>Show all dates</button>
            </p>
          )}
          {!focus && data && data.total === 0 && (
            <div className="empty">
              {noPhotos ? (
                <>
                  <h2>No photos yet</h2>
                  <p>Index your library to build the catalog. Indexing reads your photos; nothing is moved or copied.</p>
                  <button className="primary" onClick={start("index")} disabled={jobRunning}>Index your library</button>
                </>
              ) : q ? (
                <>
                  <p>No {VIEW_LABEL[view].toLowerCase()} match “{q}”.</p>
                  {(Object.keys(VIEW_LABEL) as View[]).filter((v) => v !== view && v !== "all" && data.counts[v] > 0).map((v) => (
                    <button key={v} onClick={() => setView(v)}>{count(data.counts[v])} in {VIEW_LABEL[v]}</button>
                  ))}
                </>
              ) : <p>Nothing in this view.</p>}
            </div>
          )}
          {list.meta && list.meta.total > 0 && (
            <>
              <div className="gallery-head">
                <SelectMenu onScreen={screenItems.length} screenSelected={screenSelected}
                            total={list.meta.total} selected={selected.size} max={MAX_SELECTION}
                            disabledWhy={jobRunning ? "Selection is unavailable while a job is running." : null}
                            onSelectScreen={() => toggleMany(screenItems, true)} onSelectAll={selectAll}
                            onUnselectScreen={() => toggleMany(screenItems, false)} onUnselectAll={clearSelection} />
                {jobRunning && <span className="muted">Selection is unavailable while a job is running.</span>}
              </div>
              <Pager page={visible} pages={pages} total={list.meta.total} pageSize={pageSize} onPage={onPager} onPageSize={changePageSize} continuous />
              {list.first > 1 && <div ref={topSentinel} className="page-sentinel muted">Loading more photos…</div>}
              <Gallery page={{ items: flat.items }} pageOf={flat.pageOf} selected={selected} selectable={!jobRunning} openId={openId}
                       onOpen={setOpenId} onToggle={toggle} onToggleMany={toggleMany} />
              {list.last < pages
                ? <div ref={bottomSentinel} className="page-sentinel muted">Loading more photos…</div>
                : <div className="gallery-foot">
                    <span className="muted">End of {plural(list.meta.total, "photo")}.</span>
                  </div>}
            </>
          )}
        </div>
        {openId != null && (
          <>
            <div className="divider" role="separator" aria-orientation="vertical" aria-label="Resize the photo panel"
                 tabIndex={0} onPointerDown={drag}
                 onKeyDown={(e) => {
                   if (e.key === "ArrowLeft") setWidth(currentWidth() + 40);
                   if (e.key === "ArrowRight") setWidth(currentWidth() - 40);
                 }} />
            <Inspector id={openId} width={panelWidth} onClose={() => setOpenId(null)} onStep={step} />
          </>
        )}
      </main>

      {confirm && <ConfirmDialog confirm={confirm} onClose={() => setConfirm(null)} />}
    </div>
  );
}
