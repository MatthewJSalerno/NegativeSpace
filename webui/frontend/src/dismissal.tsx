// Catalog-backed banner dismissal shared across Library, Logs and Stats.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "./api";

export interface DismissalState {
  pendingId: number | null;
  failedId: number | null;
}
type Dismissal = [number | null, (id: number) => void, DismissalState];
const Context = createContext<Dismissal | null>(null);

export function DismissedRunProvider({ children }: { children: ReactNode }) {
  const [id, setId] = useState<number | null>(null);
  const [known, setKnown] = useState(false);
  const [state, setState] = useState<DismissalState>({ pendingId: null, failedId: null });
  const pending = useRef(false);
  const revision = useRef(0);
  // Keep the catalog authoritative, including after returning from another browser.
  // An old read must not overwrite a newer, acknowledged write.
  useEffect(() => {
    let mounted = true;
    const refresh = () => {
      if (pending.current) return;
      const version = ++revision.current;
      api.uiState().then((value) => {
        if (mounted && version === revision.current) setId(value.dismissed_run);
      }, () => { /* Leave unsaved banners visible; never trust a stale browser ID. */ })
        .finally(() => { if (mounted && version === revision.current) setKnown(true); });
    };
    refresh();
    window.addEventListener("focus", refresh);
    return () => { mounted = false; window.removeEventListener("focus", refresh); };
  }, []);

  const dismiss = useCallback((run: number) => {
    if (pending.current) return;
    pending.current = true;
    ++revision.current;
    setState({ pendingId: run, failedId: null });
    // The provider outlives page navigation. A document reload before acknowledgment
    // may interrupt the write; the banner then remains, rather than claiming it saved.
    api.saveUiState({ dismissed_run: run }).then((value) => {
      setId(value.dismissed_run);
      setState({ pendingId: null, failedId: null });
    }, () => {
      setState({ pendingId: null, failedId: run });
    }).finally(() => { pending.current = false; setKnown(true); });
  }, []);

  return <Context.Provider value={[known ? id : Number.MAX_SAFE_INTEGER, dismiss, state]}>{children}</Context.Provider>;
}

export function useDismissedRun(): Dismissal {
  const value = useContext(Context);
  if (!value) throw new Error("Banner dismissal requires DismissedRunProvider");
  return value;
}
