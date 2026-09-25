import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { api, ApiError, type PhotoItem, type PhotoPage, type SelectionPage, type Sort, type Status, type Timeline, type View } from "./api";
import { count, plural } from "./format";
import { useDismissedRun, useJobFeed } from "./jobs";
import { Gallery } from "./components/Gallery";
import { Inspector } from "./components/Inspector";
import { FinishedBanner, JobDrawer } from "./components/JobDrawer";
import { PAGE_SIZES, Pager } from "./components/Pager";
import { DatesPanel, dateLabel, datePage } from "./components/DatesPanel";
import { SelectMenu } from "./components/SelectMenu";
import { Tip } from "./components/Tip";
import { ActionsMenu } from "./components/ActionsMenu";
import { LogsPage } from "./components/LogsPage";
import { follow, usePath } from "./nav";
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

type Confirm = { title: string; body: string[]; action: string; danger?: boolean; run: () => Promise<void>; onCancel?: () => void };

// Showing only a set of photos, whatever the view, search and dates would hide: the
// selection (Show only selected), or the photos a job just started on. `ids` is fixed
// on entry, so unticking a photo there leaves it on screen, unticked.
type Focus = { kind: "selection" | "job"; ids: number[]; auto?: boolean };

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
    return <div className="center-page"><SettingsDialog firstRun onClose={() => undefined} onSaved={() => setFirstRunDone(true)} /></div>;
  }
  return (
    <>
      {path === "/logs"
        ? <LogsPage onOpenSettings={() => setSettingsOpen(true)} />
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
  const [page, setPage] = useState(initial.page);
  const [pageSize, setPageSize] = useState(initial.size);
  const [undated, setUndated] = useState(initial.undated);
  const [dates, setDates] = useState<string[]>(initial.dates);
  const [openId, setOpenId] = useState<number | null>(initial.photo);
  const [data, setData] = useState<PhotoPage | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [jumpTimeline, setJumpTimeline] = useState<Timeline | null>(null);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [focusPage, setFocusPage] = useState(1);
  const [focusData, setFocusData] = useState<SelectionPage | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
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

  // The header's height, for everything that sticks below it: it grows when the
  // finished-job banner shows or the toolbar wraps on a narrow screen.
  useEffect(() => {
    if (!header.current) return;
    const observer = new ResizeObserver(([entry]) =>
      document.documentElement.style.setProperty("--header-h", `${Math.ceil(entry.target.getBoundingClientRect().height)}px`));
    observer.observe(header.current);
    return () => observer.disconnect();
  }, []);

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

  useEffect(() => {
    let live = true;
    api.photos({ view, sort, q, page, page_size: pageSize, undated, dates }).then(
      (d) => { if (live) { setData(d); setLoadError(null); } },
      (e) => live && setLoadError(e instanceof ApiError ? e.message : "Photos could not be loaded."),
    );
    return () => { live = false; };
  }, [view, sort, q, page, pageSize, undated, dates, refreshKey]);

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

  useEffect(() => {
    if (!focus) { setFocusData(null); return; }
    let live = true;
    api.selection(focus.ids, sort, focusPage, pageSize).then(
      (d) => { if (live) { setFocusData(d); setLoadError(null); } },
      (e) => live && setLoadError(e instanceof ApiError ? e.message : "The selected photos could not be loaded."),
    );
    return () => { live = false; };
  }, [focus, sort, focusPage, pageSize, refreshKey]);

  const pages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;
  const shown = focus ? focusData : data;
  const onPageIds = useMemo(() => new Set(data?.items.map((i) => i.id) ?? []), [data]);
  const outside = [...selected].filter((id) => !onPageIds.has(id)).length;
  // The month the page starts in, highlighted in the tree.
  const currentDate = sort === "newest" || sort === "oldest" ? data?.items[0]?.date_taken?.slice(0, 7) ?? null : null;

  const showSelected = () => { setFocus({ kind: "selection", ids: [...selected] }); setFocusPage(1); };
  const backToResults = () => { setFocus(null); setFocusPage(1); };

  const changeDates = (next: string[]) => { setDates(next); setPage(1); };
  const jumpTo = (key: string) => {
    const newestFirst = sort !== "oldest";
    const target = datePage(jumpTimeline ?? timeline ?? { months: [], undated: 0 }, newestFirst, pageSize, key);
    if (target == null) {
      setNotice(`${dateLabel(key)} is not in the dates shown. Tick it under Show only, or clear the date filter.`);
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
    if (!data || openId == null) return;
    const index = data.items.findIndex((i) => i.id === openId);
    const next = data.items[index + delta];
    if (next) setOpenId(next.id);
  }, [data, openId]);

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

  // Acting on a selection some of which is hidden shows the whole selection first, so
  // what the job will touch is on screen. Cancel returns to the view it came from.
  const transferSelected = (mode: "copy" | "move") => {
    const ids = [...selected];
    const auto = !focus && ids.some((id) => !onPageIds.has(id));
    if (auto) { setFocus({ kind: "selection", ids, auto: true }); setFocusPage(1); }
    askTransfer(mode, ids, auto ? backToResults : undefined);
  };

  const askTransfer = (mode: "copy" | "move", ids?: number[], onCancel?: () => void) => {
    // "All" counts what the engine would take across the whole catalog (GET /status),
    // never the gallery's view or search.
    const scope = ids ? plural(ids.length, "selected photo")
      : mode === "copy" ? `every photo not yet copied (${count(status.eligible.copy)})`
        : `every photo not yet moved (${count(status.eligible.move)})`;
    setConfirm({
      title: mode === "move" ? `Move ${scope}?` : `Copy ${scope}?`,
      action: mode === "move" ? "Move" : "Copy",
      danger: mode === "move",
      body: mode === "move" ? [
        "Each photo is copied into the destination's date folders, checked byte for byte, and only then deleted from the source.",
        ...(!ids && status.copied > 0 ? [`${plural(status.copied, "photo is", "photos are")} already copied: each of their copies is verified again before its source is deleted.`] : []),
        "Duplicate copies in the source are removed once a matching copy is confirmed at the destination.",
      ] : [
        "Each photo is copied into the destination's date folders and checked byte for byte. Nothing in the source is changed or deleted.",
      ],
      run: start(mode, ids),
      onCancel,
    });
  };

  const noPhotos = status.photos === 0;
  const tooMany = selected.size > MAX_SELECTION;

  const focusTotal = focusData?.total ?? 0;
  const focusPages = Math.max(1, Math.ceil(focusTotal / pageSize));
  const pageSelected = shown ? shown.items.filter((i) => selected.has(i.id)).length : 0;

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
              {selected.size > 0 && <button className="link" onClick={() => setSelected(new Set())}>Clear</button>}
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
              <button key={v} className={v === view ? "active" : ""} disabled={!!focus}
                      onClick={() => { setView(v); setPage(1); }}>
                {VIEW_LABEL[v]}{data ? ` (${count(data.counts[v])})` : ""}
              </button>
            ))}
            <Tip text="Photos whose EXIF has no date taken. They are filed under Undated, by their file's modification date.">
              <button className={`filter ${undated ? "active" : ""}`} aria-pressed={undated} disabled={!!focus}
                      onClick={() => { setUndated(!undated); setPage(1); }}>
                No capture date{data ? ` (${count(data.counts.undated)})` : ""}
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
          <DatesPanel timeline={timeline} dates={dates} current={currentDate} onDates={changeDates}
                      onJump={(key) => { jumpTo(key); setDatesOpen(false); }} />
        )}
        <div className="gallery-pane">
          {loadError && <p className="error">{loadError}</p>}
          {notice && <p className="notice" role="status">{notice} <button className="link" onClick={() => setNotice(null)}>Dismiss</button></p>}
          {focus && (
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
              Showing only {dates.map(dateLabel).join(", ")} · <button className="link" onClick={() => changeDates([])}>Show all dates</button>
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
          {shown && shown.total > 0 && (
            <>
              <div className="gallery-head">
                <SelectMenu onPage={shown.items.length} pageSelected={pageSelected}
                            total={focus ? focusTotal : shown.total} selected={selected.size} max={MAX_SELECTION}
                            disabledWhy={jobRunning ? "Selection is unavailable while a job is running." : null}
                            onSelectPage={() => toggleMany(shown.items, true)} onSelectAll={selectAll}
                            onUnselectPage={() => toggleMany(shown.items, false)} onUnselectAll={() => setSelected(new Set())} />
                {jobRunning && <span className="muted">Selection is unavailable while a job is running.</span>}
              </div>
              {focus
                ? <Pager page={focusPage} pages={focusPages} total={focusTotal} pageSize={pageSize} onPage={setFocusPage} onPageSize={changePageSize} />
                : <Pager page={page} pages={pages} total={shown.total} pageSize={pageSize} onPage={setPage} onPageSize={changePageSize} />}
              <Gallery page={shown} selected={selected} selectable={!jobRunning} openId={openId}
                       onOpen={setOpenId} onToggle={toggle} onToggleMany={toggleMany} />
              <div className="gallery-foot">
                {focus
                  ? <Pager page={focusPage} pages={focusPages} total={focusTotal} pageSize={pageSize} onPage={setFocusPage} onPageSize={changePageSize} />
                  : <Pager page={page} pages={pages} total={shown.total} pageSize={pageSize} onPage={setPage} onPageSize={changePageSize} />}
              </div>
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

function ConfirmDialog({ confirm, onClose }: { confirm: Confirm; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const cancel = useCallback(() => { confirm.onCancel?.(); onClose(); }, [confirm, onClose]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && cancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cancel]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && cancel()}>
      <div className="dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title">
        <h2 id="confirm-title">{confirm.title}</h2>
        {confirm.body.map((line) => <p key={line}>{line}</p>)}
        <footer className="settings-actions">
          <button onClick={cancel} disabled={busy}>Cancel</button>
          <button className={confirm.danger ? "danger" : "primary"} disabled={busy}
                  onClick={async () => { setBusy(true); await confirm.run(); onClose(); }}>
            {confirm.action}
          </button>
        </footer>
      </div>
    </div>
  );
}
