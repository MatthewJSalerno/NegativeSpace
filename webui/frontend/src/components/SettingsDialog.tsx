import { useEffect, useMemo, useState } from "react";
import { api, ApiError, type ExtensionSupport, type Settings } from "../api";

const QUEUE_SIZE = 1000; // DB_QUEUE_SIZE, fixed in the engine (engine-spec 4.1)

// Settings (webui-spec 3). A window over the current view, so closing it returns
// you to where you were; on first run it is the page itself and cannot be closed.
// Saves carry the revision each value was read at, so another tab's save is never
// silently overwritten.
export function SettingsDialog({ firstRun, onClose, onSaved }: {
  firstRun: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [workers, setWorkers] = useState("");
  const [retention, setRetention] = useState("");
  const [exts, setExts] = useState<string[]>([]);
  const [support, setSupport] = useState<Record<string, ExtensionSupport>>({});
  const [custom, setCustom] = useState("");
  const [message, setMessage] = useState<{ kind: "error" | "ok"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);

  const load = () =>
    api.settings().then((s) => {
      setSettings(s);
      setWorkers(String(s.workers.value));
      setRetention(String(s.backup_retention.value));
      setExts(s.exts.value);
      setSupport(Object.fromEntries(s.exts.support.map((e) => [e.extension, e])));
    }, (e) => setMessage({ kind: "error", text: e instanceof ApiError ? e.message : "Settings could not be loaded." }));

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (firstRun) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [firstRun, onClose]);

  // Every format the engine reads, plus any custom extension already chosen.
  const offered = useMemo(() => {
    const all = new Set([...(settings?.exts.default ?? []), ...exts]);
    return [...all].sort();
  }, [settings, exts]);

  const changed = useMemo(() => {
    if (!settings) return {};
    const out: Record<string, unknown> = {};
    if (Number(workers) !== settings.workers.value) out.workers = Number(workers);
    if (Number(retention) !== settings.backup_retention.value) out.backup_retention = Number(retention);
    if ([...exts].sort().join() !== [...settings.exts.value].sort().join()) out.exts = [...exts].sort();
    return out;
  }, [settings, workers, retention, exts]);

  const toggleExt = (ext: string) =>
    setExts((cur) => (cur.includes(ext) ? cur.filter((e) => e !== ext) : [...cur, ext]));

  const addCustom = async () => {
    const value = custom.trim();
    if (!value) return;
    try {
      const verdict = await api.validateExtension(value);
      const ext = verdict.extension;
      setSupport((s) => ({ ...s, [ext]: verdict }));
      setExts((cur) => (cur.includes(ext) ? cur : [...cur, ext]));
      setCustom("");
    } catch (e) {
      setMessage({ kind: "error", text: e instanceof ApiError ? e.message : "That extension could not be checked." });
    }
  };

  const save = async () => {
    if (!settings) return;
    setMessage(null);
    if (Object.keys(changed).length === 0) {
      if (firstRun) onSaved();
      else setMessage({ kind: "ok", text: "Nothing changed." });
      return;
    }
    if (exts.length === 0) {
      setMessage({ kind: "error", text: "Choose at least one file type." });
      return;
    }
    const revisionOf: Record<string, number> = {
      workers: settings.workers.revision, exts: settings.exts.revision, backup_retention: settings.backup_retention.revision,
    };
    const revisions = Object.fromEntries(Object.keys(changed).map((k) => [k, revisionOf[k]]));
    setSaving(true);
    try {
      const saved = await api.saveSettings(changed, revisions);
      setSettings(saved);
      setMessage({
        kind: "ok",
        text: saved.job_active ? "Saved. The running job keeps its existing settings; changes apply to future jobs." : "Saved.",
      });
      onSaved();
    } catch (e) {
      if (e instanceof ApiError && e.code === "settings_changed") {
        await load();
        setMessage({ kind: "error", text: "These settings were changed elsewhere, so nothing was saved. The current values are shown; make your change again." });
      } else {
        setMessage({ kind: "error", text: e instanceof ApiError ? e.message : "Settings were not saved." });
      }
    } finally {
      setSaving(false);
    }
  };

  const reset = () => settings && (setWorkers(String(settings.workers.value)), setRetention(String(settings.backup_retention.value)),
                                   setExts(settings.exts.value), setMessage(null));

  const body = (
    <div className={firstRun ? "settings settings-page" : "settings"} role="dialog" aria-modal={!firstRun} aria-labelledby="settings-title">
      <header className="settings-head">
        <h2 id="settings-title">{firstRun ? "Welcome to NegativeSpace" : "Settings"}</h2>
        {!firstRun && <button onClick={onClose} aria-label="Close settings">✕</button>}
      </header>
      {firstRun && (
        <div className="notice notice-first-run">
          <p><strong>These are starting values, not a one-time choice.</strong></p>
          <p>
            You can change any of them at any time in the app's Settings: the <span aria-hidden="true">⚙</span> gear
            icon at the top right of every page. Check them, then save to continue.
          </p>
        </div>
      )}
      {!settings ? <p className="muted">Loading…</p> : (
        <>
          <section>
            <h3>Worker processes</h3>
            <label className="field">
              <span>Maximum worker processes</span>
              <input type="number" min={1} value={workers} onChange={(e) => setWorkers(e.target.value)} />
            </label>
            <p className="muted">Controls how many photos are read and hashed at once.</p>
            <p className="notice">
              Detected: {settings.workers.detected} CPU cores. This is what the host reports. By default a
              container may use all of them, but a CPU limit set on the container (for example with
              {" "}<code>--cpus</code>) is not reflected in this figure. <strong>If you have set a CPU limit on
              this container, update this field to match it.</strong>
            </p>
            <p className="muted">Database queue size: {QUEUE_SIZE.toLocaleString()} items (fixed in the engine, shown for reference).</p>
          </section>
          <section>
            <h3>File types</h3>
            <div className="ext-grid">
              {offered.map((ext) => (
                <label key={ext} className={support[ext] && !support[ext].supported ? "ext unsupported" : "ext"}>
                  <input type="checkbox" checked={exts.includes(ext)} onChange={() => toggleExt(ext)} /> {ext}
                </label>
              ))}
            </div>
            {exts.filter((e) => support[e] && !support[e].supported).map((e) => (
              <p key={e} className="warning">{support[e].warning}</p>
            ))}
            <div className="field-inline">
              <input placeholder=".ext" value={custom} onChange={(e) => setCustom(e.target.value)}
                     onKeyDown={(e) => e.key === "Enter" && addCustom()} aria-label="Add a file type" />
              <button onClick={addCustom}>Add file type</button>
            </div>
          </section>
          <section>
            <h3>Catalog backups</h3>
            <label className="field">
              <span>Automatic backups to keep</span>
              <input type="number" min={1} value={retention} onChange={(e) => setRetention(e.target.value)} />
            </label>
          </section>
          <p className="notice">Changes apply to future jobs. Active jobs will continue with their existing settings.</p>
          {message && <p className={message.kind === "error" ? "error" : "ok"} role="alert">{message.text}</p>}
          <footer className="settings-actions">
            {!firstRun && <button onClick={reset} disabled={saving}>Reset</button>}
            <button className="primary" onClick={save} disabled={saving}>
              {saving ? "Saving…" : firstRun ? "Save and continue" : "Save settings"}
            </button>
          </footer>
        </>
      )}
    </div>
  );

  return firstRun ? body : (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>{body}</div>
  );
}
