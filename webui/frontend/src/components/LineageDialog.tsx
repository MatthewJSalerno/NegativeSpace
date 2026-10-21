import { useEffect, useMemo, useRef, useState } from "react";
import { MetadataHistory } from "./MetadataHistory";
import { Modal } from "./ui/Modal";
import { Tip } from "./Tip";
import { api, ApiError, type Lineage, type LineageFile, type LineageOperation } from "../api";
import { bytes, instant } from "../format";
import { follow, logUrl, photoUrl } from "../nav";
import { jobLabel } from "../jobs";
import { actionLabel, eventGroups, historySummary, LANES, laneRows, recordedNow, RETRY_MODE, shortJob, sourceLanes, timelineEvents, type LaneRow, type TimelineEvent } from "../lineage";

const datePart = (value: string, time = false) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, time
    ? { hour: "numeric", minute: "2-digit" } : { day: "numeric", month: "short", year: "numeric" });
};

export function LineageDialog({ photoId, filename, jobRunning, onOpenPhoto, onClose }: {
  photoId: number; filename: string; jobRunning: boolean;
  onOpenPhoto: (id: number) => void; onClose: () => void;
}) {
  const heading = useRef<HTMLElement>(null);
  useEffect(() => {
    const element = heading.current;
    if (!element) return;
    const observer = new ResizeObserver(() => element.parentElement?.style.setProperty(
      "--lineage-title-height", `${element.getBoundingClientRect().height}px`));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const [tree, setTree] = useState<Lineage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  useEffect(() => {
    let live = true;
    setTree(null); setError(null); setNotice(null);
    api.lineage(photoId).then(t => { if (live) setTree(t); }, e => { if (live) setError(e instanceof ApiError ? e.message : "The lineage could not be loaded."); });
    return () => { live = false; };
  }, [photoId]);
  const events = useMemo(() => tree ? timelineEvents(tree) : [], [tree]);
  const rows = useMemo(() => tree ? laneRows(tree, events) : new Map<string, LaneRow>(), [tree, events]);
  const sources = useMemo(() => tree ? sourceLanes(tree) : new Map<number, number>(), [tree]);
  const groups = useMemo(() => eventGroups(events), [events]);
  const retry = async (op: LineageOperation) => {
    const mode = RETRY_MODE[op.mode ?? ""];
    if (!mode || op.photo_id == null || retrying) return;
    setRetrying(true);
    try {
      await api.startJob({ mode, file_ids: [op.photo_id] });
      setNotice(`Retrying as a new ${mode === "index" ? "Index" : mode === "copy" ? "Copy" : "Move"}. Its progress shows at the top of the page.`);
    } catch (e) { setNotice(e instanceof ApiError ? e.message : "The retry could not be started."); }
    finally { setRetrying(false); }
  };
  const selections = tree?.selected_by.filter(selection => !tree.operations.some(op => op.run_id === selection.run_id && op.photo_id === photoId && op.files.length)) ?? [];
  const unlinked = tree?.files.filter(file => !tree.operations.some(op => op.files.some(link => link.file_id === file.file_id))) ?? [];
  const renderEvent = (event: TimelineEvent) => tree && <EventRow key={event.key} event={event} tree={tree} row={rows.get(event.key)!}
    sources={sources} jobRunning={jobRunning || retrying} onRetry={retry} onOpenPhoto={onOpenPhoto} />;
  return <Modal className="dialog lineage-dialog" labelledBy="lineage-title" onClose={onClose}>
    <header ref={heading} className="lineage-head"><h2 id="lineage-title">Lineage of {filename}</h2><button onClick={onClose} aria-label="Close">✕</button></header>
    <div className="lineage-tools">
    {unlinked.length > 0 && <details><summary>Files without a recorded operation ({unlinked.length})</summary>
      <ul>{unlinked.map(file => <li key={file.file_id}><FilePath file={file} path={file.path} photoId={photoId} onOpenPhoto={onOpenPhoto} /></li>)}</ul>
    </details>}
    {selections.length > 0 && <details><summary>Jobs without a recorded file step ({selections.length})</summary>
      <p className="section-note">This photo was selected for these jobs, but no file step was recorded. Open the job for its outcome.</p>
      <ul>{selections.map(s => <li key={s.run_id}><a href={logUrl({ run: s.run_id })} onClick={e => { onClose(); follow(e); }}>{jobLabel(s.run_id, s.mode)} · {instant(s.started_at)}</a></li>)}</ul>
    </details>}
    {tree && <MetadataHistory onNavigate={onClose} filters={{ photo: photoId, run: [], status: [], q: "", since: "", until: "" }} />}
    <p><a href={logUrl({ photo: photoId })} onClick={e => { onClose(); follow(e); }}>View photo logs</a></p>
    </div>
    <div className="lineage-pinned-head">
      {tree && <p className="lineage-summary">{historySummary(tree, events)}</p>}
      <p className="section-note">Last recorded file history, not a live disk check. Path information includes size and content fingerprint.</p>
      {tree && <div className="lineage-lane-head" aria-hidden="true">{LANES.map(lane => <span key={lane}>{lane}</span>)}</div>}
    </div>
    {notice && <p className="notice" role="status">{notice}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {!tree && !error && <p className="muted" role="status">Loading…</p>}
    {tree && <ol className="lineage-timeline" aria-label="Recorded events">
      {groups.map(group => group.length === 1 ? renderEvent(group[0]) : <CollapsedEvents key={group[0].key} events={group} rows={rows} renderEvent={renderEvent} />)}
    </ol>}
    {tree && !events.length && <p>No file operations have been recorded.</p>}
    {tree && <footer className="lineage-now">
      <LaneGraphic now row={{ before: [0, 1, 2, 3].map(lane => tree.files.some(file => file.presence === "present" && (file.role === "source" ? sources.get(file.file_id) === lane : file.place === "library" ? lane === 2 : file.place === "rejects" && lane === 3))), after: [], dots: [], curves: [], ended: [], libraryDashed: false }} />
      <div><strong>Now</strong><p>{recordedNow(tree)}</p>
        <details><summary>Recorded locations ({tree.files.length})</summary><ul>{tree.files.map(file => <li key={file.file_id}>
          <span>{file.role === "source" ? "Source" : file.place === "rejects" ? "Rejects" : "Destination"} · {file.presence ?? "Presence unknown"}: </span>
          <FilePath file={file} path={file.path} photoId={photoId} onOpenPhoto={onOpenPhoto} />
        </li>)}</ul></details>
      </div>
    </footer>}
  </Modal>;
}

function FilePath({ file, path, photoId, onOpenPhoto, indexed = false }: { indexed?: boolean; file?: LineageFile; path: string | null; photoId: number; onOpenPhoto: (id: number) => void }) {
  const details = [path, file?.file_size != null ? bytes(file.file_size) : null,
    indexed && file?.indexed_sha1 ? `At first Index: SHA-1 ${file.indexed_sha1}` : null,
    file?.sha1_hash ? `Latest recorded SHA-1 ${file.sha1_hash} (${file.matches ? "same content as this photo" : "different content"})` : null,
    file?.created_at ? `First recorded ${instant(file.created_at)}` : null].filter(Boolean).join("\n");
  return <Tip wide text={details || "No path was recorded."} content={(details || "No path was recorded.").split("\n").map((line, i) => <span key={i}>{line}</span>)}>{file?.photo_id != null && file.photo_id !== photoId
    ? <button className="link lineage-path" onClick={() => onOpenPhoto(file.photo_id!)} title={`Open photo #${file.photo_id}`}><code>{path ?? "Path not recorded"}</code></button>
    : <code className="lineage-path" tabIndex={0}>{path ?? "Path not recorded"}</code>}</Tip>;
}

function EventRow({ event, tree, row, sources, jobRunning, onRetry, onOpenPhoto }: {
  event: TimelineEvent; tree: Lineage; row: LaneRow; sources: Map<number, number>; jobRunning: boolean;
  onRetry: (op: LineageOperation) => void; onOpenPhoto: (id: number) => void;
}) {
  const [all, setAll] = useState(false);
  const first = event.operations[0];
  const paths = event.discoveries;
  return <li className="lineage-event" data-operation-ids={event.operations.map(op => op.id).join(",")}>
    <LaneGraphic row={row} count={paths.length > 1 ? paths.filter(file => sources.get(file.file_id) === 1).length : undefined} />
    <time dateTime={first.timestamp} title={instant(first.timestamp)} aria-label={instant(first.timestamp)}>{datePart(first.timestamp)}<br />{datePart(first.timestamp, true)}</time>
    <div className="lineage-event-content">
      {paths.length > 0 ? <>
        <p><a href={logUrl({ run: first.run_id, photo: tree.photo_id })} onClick={follow}><strong>{shortJob(first)}</strong></a> · Found {paths.length === 1 ? paths[0].photo_id === tree.photo_id ? "the source photo" : sources.get(paths[0].file_id) === 1 ? "an identical copy" : "a separate source file" : `${paths.length} source files`}.</p>
        <ul className="lineage-discoveries">{(all ? paths : paths.slice(0, 3)).map(file => {
          const op = event.operations.find(op => op.files.some(link => link.file_id === file.file_id))!;
          return <li key={file.file_id}><span className="section-note">{file.photo_id === tree.photo_id ? "Source" : sources.get(file.file_id) === 1 ? "Identical copy" : "Separate source file"}: </span>
            <FilePath file={file} indexed path={file.indexed_path ?? op.source_path} photoId={tree.photo_id} onOpenPhoto={onOpenPhoto} />
            <span className="section-note"> · </span><a href={logUrl({ run: op.run_id, photo: file.photo_id ?? tree.photo_id })} onClick={follow}>View in log</a>
            {op.status === "Failed" && <Failure op={op} jobRunning={jobRunning} onRetry={onRetry} />}
          </li>;
        })}</ul>
        {paths.length > 3 && <button className="link" aria-expanded={all} onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show all ${paths.length}`}</button>}
      </> : event.operations.map(op => <div key={op.id}>
        <p><a href={logUrl({ run: op.run_id, photo: tree.photo_id })} onClick={follow}><strong>{shortJob(op)}</strong></a> · <Tip text={op.error_message ?? `${actionLabel(op)}${op.recovery ? " (recovery of earlier work)" : ""}`}><strong className="lineage-step" tabIndex={0}>{actionLabel(op)}</strong></Tip>{op.recovery && <span> · Recovery of earlier work</span>}</p>
        {(["source", "destination"] as const).map(role => {
          const path = role === "source" ? op.source_path : op.consolidated_path ?? op.dest_path;
          if (!path) return null;
          const link = op.files.find(link => role === "source" ? link.role === "source" : link.role === "destination" || link.role === "retained_copy");
          const file = tree.files.find(file => file.file_id === link?.file_id);
          return <div className={`lineage-operation-path lineage-${role}`} key={role}><span className="section-note">{role === "source" ? "From" : link?.role === "retained_copy" ? "Already at" : "To"}: </span><FilePath file={file} path={path} photoId={tree.photo_id} onOpenPhoto={onOpenPhoto} /></div>;
        })}
        <a href={logUrl({ run: op.run_id, photo: tree.photo_id })} onClick={follow}>View in log</a>
        {op.consolidated_into != null && <p>Became identical; kept <a href={photoUrl(op.consolidated_into)} onClick={e => {
          if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
          e.preventDefault(); onOpenPhoto(op.consolidated_into!);
        }}>{op.consolidated_path?.split(/[\\/]/).pop() ?? `photo #${op.consolidated_into}`}</a>.</p>}
        {op.status === "Failed" && <Failure op={op} jobRunning={jobRunning} onRetry={onRetry} />}
      </div>)}
    </div>
  </li>;
}

function Failure({ op, jobRunning, onRetry }: { op: LineageOperation; jobRunning: boolean; onRetry: (op: LineageOperation) => void }) {
  return <details className="lineage-failure"><summary>Failure details</summary>
    <p className="history-detail">{op.error_message ?? "No reason was recorded."}</p>
    <p className="section-note">Check this file and fix the cause before rechecking.</p>
    {op.photo_id != null && RETRY_MODE[op.mode ?? ""] && <button onClick={() => onRetry(op)} disabled={jobRunning} title={jobRunning ? "A job is running." : undefined}>Recheck after fixing</button>}
  </details>;
}

function CollapsedEvents({ events, rows, renderEvent }: { events: TimelineEvent[]; rows: Map<string, LaneRow>; renderEvent: (event: TimelineEvent) => React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const first = events[0], last = events.at(-1)!;
  const row = { ...rows.get(last.key)!, before: rows.get(first.key)!.before };
  return <li className="lineage-group">
    <div className="lineage-event">
      <LaneGraphic row={open ? { ...row, after: row.before, curves: [], dots: [], ended: [] } : row} count={events.reduce((n, event) => n + (event.discoveries.length || event.operations.length), 0)} />
      <div className="lineage-group-label"><p>{events.length} {first.kind === "discovery" ? "Index discoveries" : actionLabel(first.operations[0]).toLowerCase()} between {datePart(first.operations[0].timestamp)} and {datePart(last.operations[0].timestamp)}.</p>
        <button className="link" aria-expanded={open} aria-controls={`lineage-group-${first.key}`} onClick={() => setOpen(!open)}>{open ? "Hide events" : "Show events"}</button></div>
    </div>
    <ol id={`lineage-group-${first.key}`} className="lineage-timeline" hidden={!open}>{events.map(renderEvent)}</ol>
  </li>;
}

function LaneGraphic({ row, count, now = false }: { row: LaneRow; count?: number; now?: boolean }) {
  const x = (lane: number) => 24 + lane * 48;
  return <div className="lineage-graph" aria-hidden="true"><svg viewBox="0 0 192 100" preserveAspectRatio="none" focusable="false">
    {LANES.map((_, lane) => <g key={lane} className={`lineage-lane-${lane}`}>
      {row.before[lane] && !(!row.after[lane] && !row.ended.includes(lane) && row.curves.some(([from, to]) => from === lane && to !== lane)) && <path d={`M ${x(lane)} 0 V 50`} strokeDasharray={lane === 2 && row.libraryDashed ? "5 4" : undefined} />}
      {!now && row.after[lane] && <path d={`M ${x(lane)} 50 V 100`} strokeDasharray={lane === 2 && (row.curves.some(c => c[1] === 3) || row.libraryDashed && !row.curves.some(c => c[1] === 2)) ? "5 4" : undefined} />}
      {row.ended.includes(lane) && <path d={`M ${x(lane) - 5} 50 h 10`} />}
    </g>)}
    {row.curves.map(([from, to, dashed], i) => <path key={i} className={`lineage-lane-${to}`} d={from === to ? `M ${x(from)} 0 C ${x(from) + 30} 20 ${x(to) + 30} 45 ${x(to)} 50` : `M ${x(from)} 0 C ${x(from)} 30 ${x(to)} 20 ${x(to)} 50`} strokeDasharray={dashed || from === 1 ? "5 4" : undefined} />)}
  </svg>{(now ? row.before.flatMap((active, lane) => active ? [lane] : []) : row.dots).map(lane => <span key={lane} className={`lineage-dot lineage-lane-${lane}${now ? " current" : ""}`} style={{ left: `${12.5 + lane * 25}%` }}>{!now && count && (lane === 1 || row.dots.length === 1) ? count : ""}</span>)}</div>;
}
