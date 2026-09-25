import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type PhotoItem, type PhotoPage, type Sort, type Status, type View } from "./api";
import { count, plural } from "./format";
import { useJobFeed } from "./jobs";
import { Gallery } from "./components/Gallery";
import { Inspector } from "./components/Inspector";
import { JobDrawer } from "./components/JobDrawer";
import { SettingsDialog } from "./components/SettingsDialog";

const PAGE_SIZE = 60;
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
    photo: p.get("photo") ? Number(p.get("photo")) : null,
  };
}

type Confirm = { title: string; body: string[]; action: string; danger?: boolean; run: () => Promise<void> };

export function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [firstRunDone, setFirstRunDone] = useState(false);

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
      <Library status={status} refreshStatus={loadStatus} onOpenSettings={() => setSettingsOpen(true)} />
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
  const [openId, setOpenId] = useState<number | null>(initial.photo);
  const [data, setData] = useState<PhotoPage | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Map<number, PhotoItem>>(new Map());
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [dismissedId, setDismissedId] = useState<number | null>(() => {
    try { return Number(localStorage.getItem("ns.dismissedRun")) || null; } catch { return null; }
  });
  const { jobs, connection } = useJobFeed();
  const jobRunning = jobs.active != null && jobs.active.presented_status !== "Interrupted";

  // A finished job changes the catalog: refresh the view and the counts. Keyed on
  // the last finished run rather than on seeing a job stop, because a job shorter
  // than one feed update is never seen running at all.
  // The first value seen is the baseline even when there is no finished run yet,
  // so the very first job on a new catalog still refreshes the view.
  const lastFinished = jobs.last && !jobRunning ? `${jobs.last.id}:${jobs.last.status}` : null;
  const seenFinished = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (seenFinished.current !== undefined && lastFinished != null && seenFinished.current !== lastFinished) {
      setRefreshKey((k) => k + 1);
      refreshStatus();
    }
    seenFinished.current = lastFinished;
  }, [lastFinished, refreshStatus]);

  useEffect(() => {
    const t = window.setTimeout(() => { setQ(search.trim()); setPage(1); }, 300);
    return () => window.clearTimeout(t);
  }, [search]);

  useEffect(() => {
    const p = new URLSearchParams();
    if (view !== "all") p.set("view", view);
    if (sort !== "newest") p.set("sort", sort);
    if (q) p.set("q", q);
    if (page > 1) p.set("page", String(page));
    if (openId != null) p.set("photo", String(openId));
    const url = `${window.location.pathname}${p.size ? `?${p}` : ""}`;
    window.history.replaceState(null, "", url);
  }, [view, sort, q, page, openId]);

  useEffect(() => {
    let live = true;
    api.photos({ view, sort, q, page, page_size: PAGE_SIZE }).then(
      (d) => { if (live) { setData(d); setLoadError(null); } },
      (e) => live && setLoadError(e instanceof ApiError ? e.message : "Photos could not be loaded."),
    );
    return () => { live = false; };
  }, [view, sort, q, page, refreshKey]);

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const onPageIds = useMemo(() => new Set(data?.items.map((i) => i.id) ?? []), [data]);
  const outside = [...selected.keys()].filter((id) => !onPageIds.has(id)).length;

  const toggle = (item: PhotoItem, on: boolean) => setSelected((cur) => {
    const next = new Map(cur);
    if (on) next.set(item.id, item); else next.delete(item.id);
    return next;
  });
  const toggleMany = (items: PhotoItem[], on: boolean) => setSelected((cur) => {
    const next = new Map(cur);
    for (const item of items) { if (on) next.set(item.id, item); else next.delete(item.id); }
    return next;
  });

  const step = useCallback((delta: number) => {
    if (!data || openId == null) return;
    const index = data.items.findIndex((i) => i.id === openId);
    const next = data.items[index + delta];
    if (next) setOpenId(next.id);
  }, [data, openId]);

  const start = (mode: "index" | "copy" | "move", fileIds?: number[]) => async () => {
    setActionError(null);
    try {
      await api.startJob(fileIds ? { mode, file_ids: fileIds } : { mode });
      if (fileIds) setSelected(new Map());
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "The job could not be started.");
    }
  };

  const askTransfer = (mode: "copy" | "move", ids?: number[]) => {
    const scope = ids ? plural(ids.length, "selected photo") : `every photo not yet organized (${count(status.photos ? (data?.counts.unorganized ?? 0) : 0)})`;
    setConfirm({
      title: mode === "move" ? `Move ${scope}?` : `Copy ${scope}?`,
      action: mode === "move" ? "Move" : "Copy",
      danger: mode === "move",
      body: mode === "move" ? [
        "Each photo is copied into the destination's date folders, checked byte for byte, and only then deleted from the source.",
        "Duplicate copies in the source are removed once a matching copy is confirmed at the destination.",
      ] : [
        "Each photo is copied into the destination's date folders and checked byte for byte. Nothing in the source is changed or deleted.",
      ],
      run: start(mode, ids),
    });
  };

  const noPhotos = status.photos === 0;
  const tooMany = selected.size > MAX_SELECTION;

  return (
    <div className={`app ${openId != null ? "with-inspector" : ""}`}>
      <header className="toolbar">
        <h1 className="brand">NegativeSpace</h1>
        <nav className="views" aria-label="Views">
          {(Object.keys(VIEW_LABEL) as View[]).map((v) => (
            <button key={v} className={v === view ? "active" : ""} onClick={() => { setView(v); setPage(1); }}>
              {VIEW_LABEL[v]}{data ? ` (${count(data.counts[v])})` : ""}
            </button>
          ))}
        </nav>
        <input className="search" type="search" placeholder="Search filenames" value={search}
               onChange={(e) => setSearch(e.target.value)} aria-label="Search filenames" />
        <select value={sort} onChange={(e) => { setSort(e.target.value as Sort); setPage(1); }} aria-label="Sort">
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
          <option value="largest">Largest first</option>
          <option value="smallest">Smallest first</option>
          <option value="name">Name</option>
        </select>
        <div className="toolbar-actions">
          <button onClick={start("index")} disabled={jobRunning} title={jobRunning ? "A job is running." : "Scan the source for new and changed photos"}>
            Scan
          </button>
          <button onClick={() => askTransfer("copy")} disabled={jobRunning || noPhotos}
                  title={noPhotos ? "Run a Scan first - NegativeSpace acts on indexed photos." : undefined}>Copy all</button>
          <button onClick={() => askTransfer("move")} disabled={jobRunning || noPhotos}
                  title={noPhotos ? "Run a Scan first - NegativeSpace acts on indexed photos." : undefined}>Move all</button>
          <button className="icon" onClick={onOpenSettings} aria-label="Settings" title="Settings">⚙</button>
        </div>
      </header>

      {actionError && <p className="error banner" role="alert">{actionError} <button onClick={() => setActionError(null)}>Dismiss</button></p>}

      <main className="content">
        <div className="gallery-pane">
          {loadError && <p className="error">{loadError}</p>}
          {data && data.total === 0 && (
            <div className="empty">
              {noPhotos ? (
                <>
                  <h2>No photos yet</h2>
                  <p>Scan your source to build the catalog. Nothing is moved or copied by a scan.</p>
                  <button className="primary" onClick={start("index")} disabled={jobRunning}>Scan the source</button>
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
          {data && data.total > 0 && (
            <>
              <div className="gallery-head">
                <button onClick={() => toggleMany(data.items, true)} disabled={jobRunning}>Select all on this page</button>
                {jobRunning && <span className="muted">Selection is unavailable while a job is running.</span>}
                <Pager page={page} pages={pages} onPage={setPage} total={data.total} />
              </div>
              <Gallery page={data} selected={selected} selectable={!jobRunning} openId={openId}
                       onOpen={setOpenId} onToggle={toggle} onToggleMany={toggleMany} />
              <div className="gallery-foot"><Pager page={page} pages={pages} onPage={setPage} total={data.total} /></div>
            </>
          )}
        </div>
        {openId != null && <Inspector id={openId} onClose={() => setOpenId(null)} onStep={step} />}
      </main>

      {selected.size > 0 && (
        <div className="action-bar" role="region" aria-label="Selection">
          <span>
            <strong>{plural(selected.size, "photo")} selected</strong>
            {outside > 0 && ` · ${count(outside)} outside this view`}
          </span>
          {tooMany && <span className="error">{count(MAX_SELECTION)} file limit for individual selection.</span>}
          {jobRunning && <span className="muted">Photo changes are unavailable while a job is running.</span>}
          <button onClick={() => askTransfer("copy", [...selected.keys()])} disabled={jobRunning || tooMany}>Copy selected</button>
          <button onClick={() => askTransfer("move", [...selected.keys()])} disabled={jobRunning || tooMany}>Move selected</button>
          <button onClick={() => setSelected(new Map())}>Clear selection</button>
        </div>
      )}

      <JobDrawer jobs={jobs} connection={connection} dismissedId={dismissedId}
                 onDismiss={(id) => { setDismissedId(id); try { localStorage.setItem("ns.dismissedRun", String(id)); } catch { /* per-viewer convenience only */ } }} />

      {confirm && <ConfirmDialog confirm={confirm} onClose={() => setConfirm(null)} />}
    </div>
  );
}

function Pager({ page, pages, total, onPage }: { page: number; pages: number; total: number; onPage: (p: number) => void }) {
  return (
    <span className="pager">
      <button onClick={() => onPage(page - 1)} disabled={page <= 1} aria-label="Previous page">‹</button>
      <span>Page {count(page)} of {count(pages)} · {plural(total, "photo")}</span>
      <button onClick={() => onPage(page + 1)} disabled={page >= pages} aria-label="Next page">›</button>
    </span>
  );
}

function ConfirmDialog({ confirm, onClose }: { confirm: Confirm; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title">
        <h2 id="confirm-title">{confirm.title}</h2>
        {confirm.body.map((line) => <p key={line}>{line}</p>)}
        <footer className="settings-actions">
          <button onClick={onClose} disabled={busy}>Cancel</button>
          <button className={confirm.danger ? "danger" : "primary"} disabled={busy}
                  onClick={async () => { setBusy(true); await confirm.run(); onClose(); }}>
            {confirm.action}
          </button>
        </footer>
      </div>
    </div>
  );
}
