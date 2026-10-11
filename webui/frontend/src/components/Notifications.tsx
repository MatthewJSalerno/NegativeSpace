import { useEffect, useRef, useState } from "react";
import { api, type NotificationPage } from "../api";
import { count, duration, instant } from "../format";
import { reasonsText, showsPhotos, summary, useJobCompletion } from "../jobs";
import { follow, logUrl } from "../nav";
import { useNotifications } from "../notifications";

export function Notifications({ onShowPhotos }: { onShowPhotos?: (id: number) => void }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<NotificationPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const state = useNotifications();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const revision = useRef(0);
  const requestedBefore = useRef<number | undefined>(undefined);
  const acknowledge = async (page: NotificationPage) => {
    const ids = page.items.filter(item => !item.read).map(item => item.run.id!);
    if (await state.markRead(ids)) setData(old => old && ({ ...old,
      items: old.items.map(item => ids.includes(item.run.id!) ? { ...item, read: true } : item) }));
  };
  const load = async (before?: number) => {
    const version = ++revision.current;
    requestedBefore.current = before;
    setLoading(true); setLoadError(false);
    try {
      const page = await api.notifications(before);
      if (version !== revision.current) return;
      setData(old => before && old ? { ...page, items: [...old.items, ...page.items] } : page);
      void acknowledge(page);
    } catch { if (version === revision.current) setLoadError(true); }
    finally { if (version === revision.current) setLoading(false); }
  };
  useJobCompletion(() => { if (open) void load(); });
  const close = () => { ++revision.current; setOpen(false); trigger.current?.focus(); };
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!root.current?.contains(e.target as Node)) close(); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);
  useEffect(() => () => { ++revision.current; }, []);
  return <div className="notifications" ref={root} onKeyDown={e => {
    if (open) e.stopPropagation();
    if (open && e.key === "Escape" && !e.defaultPrevented) { e.preventDefault(); e.stopPropagation(); close(); }
  }}>
    <button type="button" className="notification-trigger" ref={trigger} aria-expanded={open}
      aria-controls="notifications-panel" aria-label={`Notifications${state.unread == null ? ", count unavailable" : `, ${count(state.unread)} unread`}`}
      title="Notifications" onClick={() => { if (open) close(); else { setOpen(true); setData(null); void load(); } }}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" />
      </svg>
      <span className="notification-count" aria-hidden="true">{state.unread == null ? "?" : state.unread > 99 ? "99+" : count(state.unread)}</span>
    </button>
    {open && <section id="notifications-panel" className="notifications-panel" aria-label="Notifications">
      <div className="notifications-head"><h2>Notifications</h2>
        <button type="button" className="icon" aria-label="Close notifications" onClick={close}>✕</button></div>
      <p className="muted">Finished jobs, newest first. Reading a notice does not resolve its failures.</p>
      {state.unread == null && <p className="error">Unread count unavailable. <button onClick={state.refresh}>Retry count</button></p>}
      {state.pending && <p className="muted" role="status">Marking notices read…</p>}
      {state.error && <p className="error" role="alert">{state.error}{" "}
        <button disabled={state.pending || !data} onClick={() => data && void acknowledge(data)}>Retry marking read</button></p>}
      {data?.items.map(({ run, read }) => {
        const result = summary(run);
        const reasons = reasonsText(run.outcome);
        return <article key={run.id} className={`notification-item finished-${result.tone}`} aria-label={result.headline}>
          <div className="notification-heading"><h3>{result.headline}</h3>{!read && <span className="muted">Unread</span>}</div>
          <p>{result.detail}</p>
          <p className="muted">{instant(run.ended_at)}{run.started_at && run.ended_at ? ` · Took ${duration(Date.parse(run.ended_at) - Date.parse(run.started_at))}` : ""}</p>
          {!!run.questions?.length && <p className="warning">This job needs a decision. Open its log to choose how to proceed.</p>}
          <div className="notification-links">
            {showsPhotos(run) && <a href={`/?run=${run.id}`} onClick={e => {
              if (onShowPhotos && e.button === 0 && !e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey) {
                e.preventDefault(); close(); onShowPhotos(run.id!);
              } else { follow(e); setOpen(false); }
            }}>Show these photos</a>}
            {!!(run.outcome?.failed || run.outcome?.run_level_issues) && <a href={logUrl({ run: run.id!, status: "Failed" })}
              onClick={e => { follow(e); setOpen(false); }}>View failures</a>}
            <a href={logUrl({ run: run.id! })} onClick={e => { follow(e); setOpen(false); }}>View log</a>
          </div>
          {reasons && <details className="notification-details">
            <summary>Details</summary>
            <p>{reasons}</p>
          </details>}
        </article>;
      })}
      {data?.items.length === 0 && <p>No finished jobs yet.</p>}
      {loadError && <p className="error" role="alert">Could not load notifications.{" "}<button onClick={() => void load(requestedBefore.current)}>Retry</button></p>}
      {loading && <p role="status">Loading notifications…</p>}
      {!loading && !loadError && data?.next_before != null && <button onClick={() => void load(data.next_before!)}>Load older notifications</button>}
      <a href="/logs" onClick={e => { follow(e); setOpen(false); }}>All jobs in Logs</a>
    </section>}
  </div>;
}
