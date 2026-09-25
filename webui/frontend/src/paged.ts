// Continuous scrolling over a paged list (webui-spec 2): a run of loaded pages that
// grows at either end as the viewer nears it. Pages stay the unit the API serves and
// the address names, so a reload or a shared link returns to the same place.
import { useCallback, useEffect, useRef, useState } from "react";
import type { PhotoItem } from "./api";

export interface PageResult { items: PhotoItem[]; total: number }

interface Loaded<T> { key: string; pages: Map<number, PhotoItem[]>; meta: T | null; error: string | null }

// `key` names everything the list depends on except the page; a new key, or a new
// `anchor` jump, starts again from the anchor page. `refreshKey` reloads what is loaded.
export function usePaged<T extends PageResult>(fetchPage: (page: number) => Promise<T>, key: string, anchor: { page: number; n: number },
                                               pageSize: number, refreshKey: number, onError: (message: string) => void) {
  // A jump starts a new run, so a page still loading from before it cannot join it.
  const runKey = `${key}#${anchor.n}#${pageSize}`;
  const [state, setState] = useState<Loaded<T>>({ key: "", pages: new Map(), meta: null, error: null });
  const runRef = useRef(runKey);
  runRef.current = runKey;
  const loading = useRef(new Set<number>());
  const fetchRef = useRef(fetchPage);
  fetchRef.current = fetchPage;
  const current = useRef(state);
  current.current = state;

  useEffect(() => {
    let live = true;
    loading.current = new Set([anchor.page]);
    fetchRef.current(anchor.page).then(async (d) => {
      // A page past the end (the list shrank): start from the last page instead.
      const last = Math.max(1, Math.ceil(d.total / pageSize));
      let page = anchor.page;
      if (d.items.length === 0 && anchor.page > last) { page = last; d = await fetchRef.current(last); }
      if (live) setState({ key: runKey, pages: new Map([[page, d.items]]), meta: d, error: null });
    }, (e) => { if (live) { setState({ key: runKey, pages: new Map(), meta: null, error: String(e?.message ?? e) }); onError(String(e?.message ?? e)); } })
      .finally(() => loading.current.delete(anchor.page));
    return () => { live = false; };
  }, [runKey, anchor.page]);

  const seenRefresh = useRef(refreshKey);
  useEffect(() => {
    if (seenRefresh.current === refreshKey) return;
    seenRefresh.current = refreshKey;
    const loaded = [...current.current.pages.keys()];
    const at = current.current.key;
    Promise.all(loaded.map((p) => fetchRef.current(p))).then((results) => {
      setState((s) => (s.key !== at ? s : {
        ...s, pages: new Map(loaded.map((p, i) => [p, results[i].items])), meta: results[results.length - 1] ?? s.meta,
      }));
    }, () => undefined);
  }, [refreshKey]);

  const load = useCallback((page: number) => {
    const s = current.current;
    if (s.key !== runRef.current || page < 1 || s.pages.has(page) || loading.current.has(page) || !s.meta) return;
    if (page > Math.max(1, Math.ceil(s.meta.total / pageSize))) return;
    loading.current.add(page);
    const at = s.key;
    fetchRef.current(page).then((d) => setState((cur) => (cur.key !== at ? cur : {
      ...cur, pages: new Map(cur.pages).set(page, d.items), meta: d,
    })), () => undefined).finally(() => loading.current.delete(page));
  }, [pageSize]);

  // Until a new run arrives the previous one stays on screen, rather than a blank.
  const numbers = [...state.pages.keys()].sort((a, b) => a - b);
  return {
    ready: state.key === runKey,
    meta: state.meta,
    pages: state.pages,
    first: numbers[0] ?? anchor.page,
    last: numbers[numbers.length - 1] ?? anchor.page,
    load,
  };
}
