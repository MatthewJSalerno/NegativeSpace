import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "./api";
import { useJobCompletion } from "./jobs";

const Context = createContext<{
  unread: number | null; error: string | null; pending: boolean;
  refresh: () => void; markRead: (ids: number[]) => Promise<boolean>;
} | null>(null);

// One counter across page navigation; detailed outcomes load only on opening the bell.
export function NotificationsProvider({ children }: { children: ReactNode }) {
  const [unread, setUnread] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(0);
  const version = useRef(0);
  const refresh = useCallback(() => {
    const request = ++version.current;
    api.unreadNotifications().then(value => {
      if (request === version.current) setUnread(value.unread);
    }, () => { if (request === version.current) setUnread(null); });
  }, []);
  useEffect(() => {
    refresh();
    window.addEventListener("focus", refresh);
    return () => { ++version.current; window.removeEventListener("focus", refresh); };
  }, [refresh]);
  useJobCompletion(refresh);
  const markRead = useCallback(async (ids: number[]) => {
    if (!ids.length) return true;
    setPending(n => n + 1); setError(null); ++version.current;
    try {
      for (let at = 0; at < ids.length; at += 100) await api.readNotifications(ids.slice(at, at + 100));
      return true;
    } catch {
      setError("Could not mark notifications read. Try again.");
      return false;
    } finally { setPending(n => n - 1); refresh(); }
  }, [refresh]);
  return <Context.Provider value={{ unread, error, pending: pending > 0, refresh, markRead }}>{children}</Context.Provider>;
}

export function useNotifications() {
  const value = useContext(Context);
  if (!value) throw new Error("NotificationsProvider is required");
  return value;
}
