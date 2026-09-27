// Continuous scrolling retains stable photo identities and explicit page jumps.
// A failed request keeps existing content and waits for an explicit retry.
import { useCallback, useEffect, useRef, useState } from "react";
import type { PhotoItem } from "./api";

export interface PageResult<I = PhotoItem> { items: I[]; total: number }
interface Loaded<I, T> { key: string; pages: Map<number, I[]>; meta: T | null }
interface Requests { key: string; pending: Set<number>; failures: Map<number, string> }
const message = (e: unknown) => e instanceof Error ? e.message : String(e);

export function usePaged<T extends PageResult<I>, I = PhotoItem>(fetchPage: (page: number) => Promise<T>, key: string,
  anchor: { page: number; n: number }, pageSize: number, refreshKey: number, onError: (message: string) => void) {
  const runKey = `${key}#${anchor.n}#${anchor.page}#${pageSize}`;
  const [state, setState] = useState<Loaded<I, T>>({ key: "", pages: new Map(), meta: null });
  const [requests, setRequests] = useState<Requests>({ key: "", pending: new Set(), failures: new Map() });
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [retryRefresh, setRetryRefresh] = useState(0);
  const runRef = useRef(runKey); runRef.current = runKey;
  const requestRef = useRef(requests);
  const fetchRef = useRef(fetchPage); fetchRef.current = fetchPage;
  const current = useRef(state); current.current = state;
  const publish = (r: Requests) => { if (requestRef.current !== r) return; setRequests({ ...r, pending: new Set(r.pending), failures: new Map(r.failures) }); };

  useEffect(() => {
    let live = true;
    const r: Requests = { key: runKey, pending: new Set([anchor.page]), failures: new Map() };
    requestRef.current = r; publish(r); setRefreshError(null);
    const initial = async () => {
      try {
        let page = anchor.page, data = await fetchRef.current(page);
        const last = Math.max(1, Math.ceil(data.total / pageSize));
        if (!data.items.length && page > last) { page = last; data = await fetchRef.current(page); }
        if (live) setState({ key: runKey, pages: new Map([[page, data.items]]), meta: data });
      } catch (e) {
        if (live) { setState({ key: runKey, pages: new Map(), meta: null }); onError(message(e)); }
      } finally { r.pending.delete(anchor.page); if (live) publish(r); }
    };
    void initial();
    return () => { live = false; };
  }, [runKey]);

  const seenRefresh = useRef(`${refreshKey}:${retryRefresh}`);
  useEffect(() => {
    const revision = `${refreshKey}:${retryRefresh}`;
    if (seenRefresh.current === revision) return;
    seenRefresh.current = revision;
    let live = true;
    const loaded = [...current.current.pages.keys()], at = current.current.key;
    Promise.all(loaded.map((p) => fetchRef.current(p))).then((results) => {
      if (!live || runRef.current !== at) return;
      setRefreshError(null);
      setState((s) => s.key !== at ? s : { ...s, pages: new Map(loaded.map((p, i) => [p, results[i].items])), meta: results.at(-1) ?? s.meta });
    }, (e) => { if (live && runRef.current === at) setRefreshError(message(e)); });
    return () => { live = false; };
  }, [refreshKey, retryRefresh]);

  const load = useCallback((page: number, retry = false) => {
    const s = current.current, r = requestRef.current;
    if (s.key !== runRef.current || r.key !== s.key || page < 1 || s.pages.has(page) || r.pending.has(page) || !s.meta) return;
    if ((!retry && r.failures.has(page)) || page > Math.max(1, Math.ceil(s.meta.total / pageSize))) return;
    r.pending.add(page); r.failures.delete(page); publish(r);
    fetchRef.current(page).then((data) => {
      if (runRef.current !== r.key || requestRef.current !== r) return;
      setState((cur) => cur.key !== r.key ? cur : { ...cur, pages: new Map(cur.pages).set(page, data.items), meta: data });
    }, (e) => { r.failures.set(page, message(e)); }).finally(() => { r.pending.delete(page); publish(r); });
  }, [pageSize]);
  const numbers = [...state.pages.keys()].sort((a, b) => a - b);
  return { ready: state.key === runKey, meta: state.meta, pages: state.pages,
    first: numbers[0] ?? anchor.page, last: numbers.at(-1) ?? anchor.page, load,
    pending: requests.key === runKey ? requests.pending : new Set<number>(),
    failures: requests.key === runKey ? requests.failures : new Map<number, string>(),
    refreshError, retryRefresh: () => setRetryRefresh((n) => n + 1) };
}
