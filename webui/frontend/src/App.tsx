import { useCallback, useEffect, useState } from "react";
import { api, type Status } from "./api";
import { CatalogProblem, FirstRun } from "./components/FirstRun";
import { LibraryPage } from "./components/LibraryPage";
import { LogsPage } from "./components/LogsPage";
import { SettingsDialog } from "./components/SettingsDialog";
import { SimilarRedirect } from "./components/SimilarRedirect";
import { StatsPage } from "./components/StatsPage";
import { navigate, usePath } from "./nav";

// The page shell: the catalog's state decides what shows (first run, a catalog problem,
// setup), then the address picks the page.
export function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsGroup, setSettingsGroup] = useState<"appearance" | "files" | "backups">("appearance");
  useEffect(() => {
    const open = () => { setSettingsGroup("files"); setSettingsOpen(true); };
    window.addEventListener("ns-review-settings", open);
    return () => window.removeEventListener("ns-review-settings", open);
  }, []);
  const [firstRunDone, setFirstRunDone] = useState(false);
  const path = usePath();

  const loadStatus = useCallback(() =>
    api.status().then((s) => { setStatus(s); setStatusError(null); },
                      () => setStatusError("The NegativeSpace server is not answering. Check that the container is running.")), []);
  useEffect(() => { loadStatus(); }, [loadStatus]);
  // Rejects is emptied in a file manager: coming back to the page shows the result.
  useEffect(() => {
    window.addEventListener("focus", loadStatus);
    return () => window.removeEventListener("focus", loadStatus);
  }, [loadStatus]);

  if (statusError) return <div className="center-page"><p className="error">{statusError}</p></div>;
  if (!status) return <div className="center-page muted">Loading…</div>;
  if (status.state === "missing") return <FirstRun status={status} onCreated={loadStatus} />;
  if (status.state !== "ok") return <CatalogProblem status={status} />;
  // First run: nothing indexed yet, so settings are the destination (webui-spec 3).
  if (!status.indexed && !firstRunDone) {
    // Saved, the user lands in Not organized, where Index source waits: never on the
    // page an earlier session left in the address bar.
    return <div className="center-page"><SettingsDialog firstRun onClose={() => undefined}
                                                        onSaved={() => { navigate("/"); setFirstRunDone(true); }} /></div>;
  }
  return (
    <>
      <a className="skip-link" href="#main-content">Skip to main content</a>
      {path === "/logs"
        ? <LogsPage status={status} refreshStatus={loadStatus} onOpenSettings={() => { setSettingsGroup("appearance"); setSettingsOpen(true); }} />
        : path === "/stats"
          ? <StatsPage status={status} refreshStatus={loadStatus} onOpenSettings={(group = "appearance") => { setSettingsGroup(group); setSettingsOpen(true); }} />
          : path === "/similar"
            ? <SimilarRedirect />
            : <LibraryPage status={status} refreshStatus={loadStatus} onOpenSettings={() => { setSettingsGroup("appearance"); setSettingsOpen(true); }} />}
      {settingsOpen && <SettingsDialog initialGroup={settingsGroup} firstRun={false} onClose={() => setSettingsOpen(false)} onSaved={() => { void loadStatus(); window.dispatchEvent(new Event("ns-settings-saved")); }} />}
    </>
  );
}
