import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, type Stats, type Status } from "../api";
import { bytes, count, instant, photoDate, plural } from "../format";
import { useDismissedRun, useJobFeed } from "../jobs";
import { follow, useHeaderHeight } from "../nav";
import { ActionsMenu } from "./ActionsMenu";
import { ConfirmDialog, transferConfirm, type Confirm } from "./Confirm";
import { FinishedBanner, JobDrawer } from "./JobDrawer";
import { Logo } from "./Logo";
import { VersionTag } from "./VersionTag";

const FAILURE_LABEL: Record<string, [string, string]> = {
  not_an_image: ["Not an image", "Not an image"],
  permission: ["Permission denied", "Permission"],
  changed_since_index: ["Changed since the last Index", "Source file changed"],
  duplicate_check: ["Duplicate check failed", "Duplicate verification failed"],
  no_space: ["Not enough space", "Insufficient space"],
  other: ["Other reasons", ""],
};
const JOB_LABEL: Record<string, string> = {
  INDEX: "Index", COPY: "Copy", MOVE: "Move", RENAME: "Rename", REBUILD: "Thumbnail rebuild", CHECK: "Destination check",
};

// The Stats page (webui-spec 5.9): what the catalog records about the library, its
// dates and duplicates, the work done, and the catalog's own health. Most figures
// link to the photos or log entries behind them. Only recorded figures: one that
// needs an unbuilt feature says so rather than showing a guess.
export function StatsPage({ status, refreshStatus, onOpenSettings }: {
  status: Status;
  refreshStatus: () => void;
  onOpenSettings: () => void;
}) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [dismissedId, dismissRun] = useDismissedRun();
  const { jobs, connection } = useJobFeed();
  const jobRunning = jobs.active != null && jobs.active.presented_status !== "Interrupted";
  const header = useRef<HTMLElement>(null);
  useHeaderHeight(header);

  // A job finishing changes the figures.
  const lastKey = jobs.last && !jobRunning ? `${jobs.last.id}:${jobs.last.status}` : null;
  useEffect(() => {
    let live = true;
    api.stats().then((s) => live && setStats(s),
      (e) => live && setError(e instanceof ApiError ? e.message : "The stats could not be loaded."));
    if (lastKey) refreshStatus();
    return () => { live = false; };
  }, [lastKey]);

  const startJob = (mode: "index" | "copy" | "move") => async () => {
    try { await api.startJob({ mode }); } catch (e) { setError(e instanceof ApiError ? e.message : "The job could not be started."); }
  };

  return (
    <div className="app">
      <header className="toolbar" ref={header}>
        <div className="toolbar-row">
          <h1 className="brand"><Logo />NegativeSpace</h1>
          <nav className="pages" aria-label="Pages">
            <a className="button-link" href="/" onClick={follow}>Library</a>
            <ActionsMenu
              state={{ jobRunning, noPhotos: status.photos === 0, selected: 0, tooMany: false, maxSelection: 1000,
                       eligible: status.eligible, copied: status.copied }}
              onIndex={startJob("index")}
              onTransfer={(mode) => setConfirm(transferConfirm(mode, status, undefined, startJob(mode)))} />
            <a className="button-link" href="/logs" onClick={follow}>Logs</a>
          </nav>
          <div className="toolbar-actions">
            <VersionTag version={status.version} />
            <StatsLink active />
            <button className="icon" onClick={onOpenSettings} aria-label="Settings" title="Settings">⚙</button>
          </div>
        </div>
        <JobDrawer jobs={jobs} connection={connection} />
        <FinishedBanner jobs={jobs} dismissedId={dismissedId} onDismiss={dismissRun} />
      </header>

      <main className="stats">
        <h2>Stats</h2>
        {error && <p className="error">{error}</p>}
        {!stats && !error && <p className="muted">Loading…</p>}
        {stats && <StatsBody s={stats} onOpenSettings={onOpenSettings} />}
      </main>
      {confirm && <ConfirmDialog confirm={confirm} onClose={() => setConfirm(null)} />}
    </div>
  );
}

// The Stats icon, beside Settings on every page.
export function StatsLink({ active = false }: { active?: boolean }) {
  return (
    <a className={`icon stats-link ${active ? "active" : ""}`} href="/stats" onClick={follow}
       aria-label="Stats" title="Stats" aria-current={active ? "page" : undefined}>
      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"
           fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        <path d="M5 20V11M12 20V5M19 20v-7" />
      </svg>
    </a>
  );
}

// A share as a percentage that never rounds to all or nothing: 4,681 of 4,684 reads
// 99.9%, not 100%, and 100% means every one.
function share(n: number, of: number): string {
  if (!of) return "–";
  const exact = (100 * n) / of;
  if (n === of || n === 0 || (exact >= 0.5 && exact < 99.5)) return `${Math.round(exact)}%`;
  const tenths = Math.round(exact * 10) / 10;
  return tenths >= 100 ? ">99.9%" : tenths <= 0 ? "<0.1%" : `${tenths}%`;
}

function StatsBody({ s, onOpenSettings }: { s: Stats; onOpenSettings: () => void }) {
  const lib = s.library;
  const failed = Object.values(s.activity.failures).reduce((a, b) => a + b, 0);
  return (
    <>
      <div className="stat-tiles">
        <Tile label="Photos" value={count(lib.photos)} sub={bytes(lib.bytes)} href="/" />
        <Tile label="Organized" value={share(lib.organized, lib.photos)}
              sub={`${count(lib.organized)} of ${count(lib.photos)}`} href="/?view=organized" />
        <Tile label="No capture date" value={count(s.dates.undated)}
              sub={`${share(s.dates.undated, lib.photos)} of photos`} href="/?undated=1" />
        <Tile label="Duplicate copies" value={count(s.duplicates.extra_copies)}
              sub={`${bytes(s.duplicates.bytes)} in extra copies`} />
        <Tile label="Failed attempts" value={count(failed)} sub={failed ? "Open the Error Center" : "None"}
              href={failed ? "/logs?status=Failed" : undefined} tone={failed ? "bad" : undefined} />
        <Tile label="Last backup" value={s.health.last_backup ? photoDate(s.health.last_backup, false) : "None"}
              sub={s.health.unbacked_changes ? `${count(s.health.unbacked_changes)} changes since` : "Up to date"}
              onClick={onOpenSettings} tone={s.health.unbacked_changes ? "warn" : undefined} />
      </div>

      <div className="stat-panels">
        <Panel title="Your library">
          <Facts rows={[
            ["Photos", `${plural(lib.photos, "photo")} · ${bytes(lib.bytes)}`],
            ["Organized", <a key="o" href="/?view=organized" onClick={follow}>{plural(lib.organized, "photo")} · {bytes(lib.organized_bytes)}</a>],
            ["Not yet organized", <a key="n" href="/?view=unorganized" onClick={follow}>{plural(lib.not_organized, "photo")}</a>],
            ["With a location (GPS)", `${plural(lib.with_location, "photo")} · ${share(lib.with_location, lib.photos)} of them`],
            ["Orientation", `${count(lib.orientation.landscape)} landscape · ${count(lib.orientation.portrait)} portrait · ${count(lib.orientation.square)} square`],
          ]} />
          <h4>Formats, by space</h4>
          <Bars rows={lib.formats.map((f) => ({ label: f.format.toUpperCase(), value: f.bytes, text: `${bytes(f.bytes)} · ${plural(f.photos, "photo")}`,
                                                href: `/?type=${encodeURIComponent(f.format)}` }))} />
          <h4>Resolution</h4>
          <Bars rows={lib.megapixels.map((m) => ({ label: m.band, value: m.photos, text: count(m.photos) }))} />
          {lib.under_1mp > 0 && <p className="muted">{plural(lib.under_1mp, "photo is", "photos are")} under 1 megapixel: often thumbnails or screenshots.</p>}
        </Panel>

        <Panel title="Cameras and lenses">
          {lib.cameras.length === 0 ? <p className="muted">No camera recorded in any photo's EXIF.</p>
            : <Bars rows={lib.cameras.map((c) => ({ label: c.name, value: c.photos, text: count(c.photos) }))} />}
          {lib.lenses.length > 0 && (
            <>
              <h4>Lenses</h4>
              <Bars rows={lib.lenses.map((c) => ({ label: c.name, value: c.photos, text: count(c.photos) }))} />
            </>
          )}
        </Panel>

        <Panel title="Dates">
          <YearChart years={s.dates.per_year} />
          <Facts rows={[
            ["Oldest photo", s.dates.oldest ? photoDate(s.dates.oldest, false) : "–"],
            ["Newest photo", s.dates.newest ? photoDate(s.dates.newest, false) : "–"],
            ["Busiest day", s.dates.busiest_day ? `${photoDate(s.dates.busiest_day.day, false)} · ${plural(s.dates.busiest_day.photos, "photo")}` : "–"],
            ["No capture date", <a key="u" href="/?undated=1" onClick={follow}>{count(s.dates.undated)}</a>],
            ["  no date in the EXIF", count(s.dates.undated_no_date)],
            ["  an unusable date (e.g. 0000:00:00)", count(s.dates.undated_unusable)],
            ["Recorded a time zone", count(s.dates.with_time_zone)],
          ]} />
        </Panel>

        <Panel title="Duplicates">
          <Facts rows={[
            ["Photos with exact copies", plural(s.duplicates.groups, "photo")],
            ["Extra copies", `${plural(s.duplicates.extra_copies, "file")} · ${bytes(s.duplicates.bytes)}`],
            ["Saved at the destination", <Tipped key="s" tip="Extra copies of photos already copied or moved: the destination holds one copy, not two. A duplicate of a photo not yet delivered has saved nothing so far.">{`${bytes(s.duplicates.saved_at_destination)} · ${plural(s.duplicates.copies_not_written, "duplicate file")} not copied`}</Tipped>],
            ["A Move would free in the source", <Tipped key="m" tip="Extra copies still in the source: a Move removes each once a copy of its content is verified at the destination.">{bytes(s.duplicates.move_would_free)}</Tipped>],
            ["Freed by earlier Moves", bytes(s.duplicates.freed_by_moves)],
            ["Near-duplicates (resized, re-saved)", <span key="nd" className="muted">Not recorded yet: they arrive with the Similar tab</span>],
          ]} />
          <Coverage c={s.duplicates.coverage} />
          {s.duplicates.by_folder.length > 1 && (
            <>
              <h4>By folder (the copy indexed first counts as the original)</h4>
              <table className="stat-facts stat-folders">
                <thead><tr><th>Folder</th><td>Files</td><td>Duplicates</td><td>Their size</td></tr></thead>
                <tbody>
                  {s.duplicates.by_folder.map((f) => (
                    <tr key={f.folder}>
                      <th title={f.folder || "Files directly in the source folder"}>{f.folder || "(top level)"}</th>
                      <td>{count(f.files)}</td><td>{count(f.duplicates)}</td><td>{bytes(f.duplicate_bytes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </Panel>

        <Panel title="Activity">
          <Facts rows={[
            ["Jobs run", Object.entries(s.activity.jobs).map(([m, n]) => `${JOB_LABEL[m] ?? m} ${count(n)}`).join(" · ") || "None yet"],
            ["Last Index", s.activity.last_index ? instant(s.activity.last_index) : "Never"],
            ["Copied · moved", `${plural(s.activity.copied, "photo")} copied · ${count(s.activity.moved)} moved`],
            ["Transferred", `${bytes(s.activity.bytes_transferred)}${s.activity.bytes_per_second ? ` · about ${bytes(s.activity.bytes_per_second)}/s` : ""}`],
            ["Renamed", count(s.activity.renames)],
            ["EXIF edits", <span key="e" className="muted">Not built yet</span>],
          ]} />
          <h4>Failed attempts, by reason</h4>
          {Object.keys(s.activity.failures).length === 0 ? <p className="muted">None.</p> : (
            <ul className="stat-links">
              {Object.entries(s.activity.failures).sort((a, b) => b[1] - a[1]).map(([kind, n]) => {
                const [label, search] = FAILURE_LABEL[kind] ?? [kind, ""];
                const p = new URLSearchParams({ status: "Failed" });
                if (search) p.set("q", search);
                return <li key={kind}><a href={`/logs?${p}`} onClick={follow}>{label}</a> <span className="muted">{count(n)}</span></li>;
              })}
            </ul>
          )}
        </Panel>

        <Panel title="Catalog health">
          <Facts rows={[
            ["Last backup", s.health.last_backup ? instant(s.health.last_backup) : "None yet"],
            ["Not yet backed up", s.health.unbacked_changes ? plural(s.health.unbacked_changes, "change") : "Nothing"],
            ["Backups kept", `${plural(s.health.backups, "backup")} · ${bytes(s.health.backup_bytes)}`],
            ["Catalog size", bytes(s.health.catalog_bytes)],
            ...s.health.thumbnail_cache.map((c): [string, ReactNode] =>
              [c.size <= 320 ? "Grid thumbnails" : "Detail previews", `${plural(c.photos, "photo")} · ${bytes(c.bytes)}`]),
            ["Last destination check", s.health.destination_check
              ? `${instant(s.health.destination_check.at)} · ${Object.entries(s.health.destination_check.findings)
                  .map(([k, n]) => `${count(n)} ${k}`).join(", ") || "all as recorded"}`
              : "Never run"],
          ]} />
          <button className="link" onClick={onOpenSettings}>Open Settings for backups</button>
        </Panel>
      </div>
    </>
  );
}

// How current the duplicate figures are (webui-spec 5.9): the last complete scan, and
// the scans since that had issues, linking to every run since so the gap is visible.
function Coverage({ c }: { c: Stats["duplicates"]["coverage"] }) {
  const since = new URLSearchParams();
  c.run_ids_since.forEach((r) => since.append("run", String(r)));
  const link = c.scans_with_issues_since > 0 && (
    <a href={`/logs?${since}`} onClick={follow}>{plural(c.scans_with_issues_since, "later scan")} had issues</a>);
  return (
    <p className="muted">
      {c.last_complete_scan ? <>Last complete scan: {instant(c.last_complete_scan)}{link && <> — {link}</>}.</>
        : <>Not fully scanned yet{c.run_ids_since.length > 0 && <> — <a href={`/logs?${since}`} onClick={follow}>see the scans so far</a></>}.</>}
    </p>
  );
}

function Tile({ label, value, sub, href, onClick, tone }: {
  label: string; value: string; sub: string; href?: string; onClick?: () => void; tone?: "bad" | "warn";
}) {
  const body = <><span className="tile-label">{label}</span><strong className="tile-value">{value}</strong><span className="tile-sub">{sub}</span></>;
  const cls = `stat-tile ${tone ? `tile-${tone}` : ""}`;
  if (href) return <a className={cls} href={href} onClick={follow}>{body}</a>;
  if (onClick) return <button className={cls} onClick={onClick}>{body}</button>;
  return <div className={cls}>{body}</div>;
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return <section className="stat-panel"><h3>{title}</h3>{children}</section>;
}

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <table className="stat-facts">
      <tbody>{rows.map(([k, v]) => <tr key={k}><th className={k.startsWith("  ") ? "sub" : undefined}>{k.trim()}</th><td>{v}</td></tr>)}</tbody>
    </table>
  );
}

function Tipped({ tip, children }: { tip: string; children: ReactNode }) {
  return <span className="tip" data-tip={tip} tabIndex={0}>{children}</span>;
}

// One series, so one colour and no legend; each bar names its value beside it.
function Bars({ rows }: { rows: { label: string; value: number; text: string; href?: string }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="stat-bars">
      {rows.map((r) => (
        <li key={r.label} title={`${r.label}: ${r.text}`}>
          {r.href ? <a className="bar-label" href={r.href} onClick={follow} title={`Show only ${r.label} in the Library`}>{r.label}</a>
                  : <span className="bar-label">{r.label}</span>}
          <span className="bar-track"><span className="bar-fill" style={{ width: `${Math.max(r.value ? 2 : 0, (100 * r.value) / max)}%` }} /></span>
          <span className="bar-value">{r.text}</span>
        </li>
      ))}
    </ul>
  );
}

// Photos per year: a single series, each bar a link to that year in the Library, its
// count on hover and focus; the same figures in a table beneath.
function YearChart({ years }: { years: { year: string; photos: number }[] }) {
  if (years.length === 0) return <p className="muted">No photo has a date taken yet.</p>;
  const max = Math.max(...years.map((y) => y.photos));
  return (
    <figure className="year-chart">
      <figcaption>Photos per year (date taken)</figcaption>
      <div className="year-bars" role="list">
        {years.map((y) => (
          <a key={y.year} role="listitem" className="year-bar" href={`/?date=${y.year}`} onClick={follow}
             title={`${y.year}: ${plural(y.photos, "photo")}`} aria-label={`${y.year}: ${plural(y.photos, "photo")}`}>
            <span className="year-fill" style={{ height: `${Math.max(2, (100 * y.photos) / max)}%` }} />
            <span className="year-label">{years.length > 16 && Number(y.year) % 5 ? "" : y.year}</span>
          </a>
        ))}
      </div>
      <details>
        <summary>As a table</summary>
        <table className="stat-facts"><tbody>
          {years.map((y) => <tr key={y.year}><th>{y.year}</th><td>{count(y.photos)}</td></tr>)}
        </tbody></table>
      </details>
    </figure>
  );
}
