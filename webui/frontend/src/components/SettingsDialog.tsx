import { Logo } from "./Logo";
import { Modal } from "./ui/Modal";
import { Field } from "./ui/Field";
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { api, ApiError, type AccessSettings, type ExtensionSupport, type Settings } from "../api";
import { BackupsPanel } from "./BackupsPanel";
import { setPalette, usePalette, setTheme, useTheme, type Theme } from "../appearance";
import { TabList, tabPanel } from "./ui/Tabs";

const QUEUE_SIZE = 1000; // DB_QUEUE_SIZE, fixed in the engine (engine-spec 4.1)

// The groups, in order: tabs in Settings, steps on first run (webui-spec 3).
type Group = "appearance" | "files" | "backups" | "performance" | "access";
const GROUPS: { value: Group; label: string }[] = [
  { value: "appearance", label: "Appearance" }, { value: "files", label: "Files" },
  { value: "backups", label: "Backups" }, { value: "performance", label: "Performance" }, { value: "access", label: "Access" },
];
// Where each field and each saved setting lives.
const FIELD_GROUP: Record<string, Group> = {
  workers: "performance", retention: "backups", exts: "files", reminderSize: "files", reminderAge: "files", small: "files", year: "files",
};
const SETTING_GROUP: Record<string, Group> = {
  workers: "performance", backup_retention: "backups", exts: "files",
  rejects_reminder_bytes: "files", rejects_reminder_days: "files", small_image_min: "files", suspicious_min_year: "files",
};

// Settings (webui-spec 3). A window over the current view, so closing it returns
// you to where you were, in tabs with one Save for all of them; a tab with unsaved
// changes shows a dot. On first run it is the page itself, cannot be closed, and steps
// through the same groups, saving at the end. Saves carry the revision each value was
// read at, so another browser tab's save is never silently overwritten.
export function SettingsDialog({ firstRun, onClose, onSaved, initialGroup = "appearance" }: {
  initialGroup?: Group;
  firstRun: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const palette = usePalette();
  const theme = useTheme();
  const [minYear, setMinYear] = useState("1800");
  const [access, setAccess] = useState<AccessSettings | null>(null);
  const [addresses, setAddresses] = useState("");
  const [confirmAddress, setConfirmAddress] = useState(false);
  const addressList = addresses.split(",").map(s => s.trim()).filter(Boolean);
  const accessChanged = access != null && JSON.stringify(addressList) !== JSON.stringify(access.hosts);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [workers, setWorkers] = useState("");
  const [retention, setRetention] = useState("");
  const [exts, setExts] = useState<string[]>([]);
  // The Rejects reminder's limits; off is saved as null. Size is shown in GB.
  const [smallChoice, setSmallChoice] = useState("");
  const [smallMin, setSmallMin] = useState("800");
  const [sizeOn, setSizeOn] = useState(true);
  const [sizeGb, setSizeGb] = useState("");
  const [ageOn, setAgeOn] = useState(true);
  const [ageDays, setAgeDays] = useState("");
  const [support, setSupport] = useState<Record<string, ExtensionSupport>>({});
  const [custom, setCustom] = useState("");
  const [message, setMessage] = useState<{ kind: "error" | "ok"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [group, setGroup] = useState<Group>(initialGroup);
  const idBase = useId();

  const load = () =>
    Promise.all([api.settings(), api.access()]).then(([s, a]) => {
      setAccess(a); setAddresses(a.hosts.join(", "));
      setSettings(s);
      setWorkers(String(s.workers.value));
      setRetention(String(s.backup_retention.value));
      setExts(s.exts.value);
      showReminder(s);
      setSupport(Object.fromEntries(s.exts.support.map((e) => [e.extension, e])));
    }, (e) => setMessage({ kind: "error", text: e instanceof ApiError ? e.message : "Settings could not be loaded." }));

  useEffect(() => {
    load();
  }, []);

  function showReminder(s: Settings) {
    setMinYear(String(s.suspicious_min_year.value));
    setSmallChoice(firstRun && s.small_image_min.revision === 0 ? "" : s.small_image_min.value == null ? "off" : "on");
    setSmallMin(String(s.small_image_min.value ?? 800));
    const size = s.rejects_reminder_bytes.value, days = s.rejects_reminder_days.value;
    setSizeOn(size != null);
    setSizeGb(String(Number(((size ?? s.rejects_reminder_bytes.default ?? 1e9) / 1e9).toFixed(2))));
    setAgeOn(days != null);
    setAgeDays(String(days ?? s.rejects_reminder_days.default ?? 30));
  }
  const reminderBytes = sizeOn ? Math.round(Number(sizeGb) * 1e9) : null;
  const reminderDays = ageOn ? Number(ageDays) : null;

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
    if (reminderBytes !== settings.rejects_reminder_bytes.value) out.rejects_reminder_bytes = reminderBytes;
    if (reminderDays !== settings.rejects_reminder_days.value) out.rejects_reminder_days = reminderDays;
    if (Number(minYear) !== settings.suspicious_min_year.value) out.suspicious_min_year = Number(minYear);
    const small = smallChoice === "on" ? Number(smallMin) : null;
    if (small !== settings.small_image_min.value || (firstRun && smallChoice && settings.small_image_min.revision === 0)) out.small_image_min = small;
    return out;
  }, [settings, workers, retention, exts, reminderBytes, reminderDays, smallChoice, smallMin, minYear]);

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

  const unsaved = new Set(Object.keys(changed).map((k) => SETTING_GROUP[k]));
  if (accessChanged) unsaved.add("access");

  const check = (only?: Group) => {
    const errors: Record<string, string> = {};
    if (!Number.isInteger(Number(minYear)) || Number(minYear)<1 || Number(minYear)>9999) errors.year = "Enter a whole year from 1 to 9999.";
    if (firstRun && !smallChoice) errors.small = "Choose whether to suggest small images for review.";
    if (smallChoice === "on" && (!Number.isSafeInteger(Number(smallMin)) || Number(smallMin)<1)) errors.small = "Enter a positive whole number of pixels.";
    if (!Number.isSafeInteger(Number(workers)) || Number(workers) < 1) errors.workers = "Enter a whole number of workers, at least 1.";
    if (!Number.isSafeInteger(Number(retention)) || Number(retention) < 1) errors.retention = "Enter a whole number of backups, at least 1.";
    if (!exts.length) errors.exts = "Choose at least one file type.";
    if (sizeOn && !(Number(sizeGb) >= 0.1)) errors.reminderSize = "Enter a size of at least 0.1 GB, or switch the size limit off.";
    if (ageOn && (!Number.isSafeInteger(Number(ageDays)) || Number(ageDays) < 1)) errors.reminderAge = "Enter a whole number of days, at least 1, or switch the age limit off.";
    const shown = Object.fromEntries(Object.entries(errors).filter(([k]) => !only || FIELD_GROUP[k] === only));
    setFieldErrors(shown);
    const first = Object.keys(shown)[0];
    if (first) {
      setGroup(FIELD_GROUP[first]);
      requestAnimationFrame(() => document.getElementById(first === "small" && smallChoice !== "on" ? "settings-small-choice" : `settings-${first}`)?.focus());
    }
    return !first;
  };

  // First run: Next checks only this step's fields; nothing is saved until the last.
  const step = GROUPS.findIndex((g) => g.value === group);
  const next = () => {
    setMessage(null);
    if (check(group)) setGroup(GROUPS[step + 1].value);
  };

  const save = async (confirmCurrent = false) => {
    if (!settings || !access) return;
    setMessage(null);
    if (!check()) {
      setMessage({ kind: "error", text: "Check the highlighted settings. Nothing was saved." });
      return;
    }
    const removesCurrent = accessChanged && ![...access.protected_hosts, ...addressList.map(s => s.toLowerCase().replace(/\.$/, ""))].includes(access.current_host);
    if (removesCurrent && !confirmCurrent) { setConfirmAddress(true); return; }
    setConfirmAddress(false);
    if (Object.keys(changed).length === 0 && !accessChanged) {
      if (firstRun) onSaved();
      else setMessage({ kind: "ok", text: "Nothing changed." });
      return;
    }
    const revisionOf: Record<string, number> = {
      suspicious_min_year: settings.suspicious_min_year.revision,
      small_image_min: settings.small_image_min.revision, workers: settings.workers.revision, exts: settings.exts.revision, backup_retention: settings.backup_retention.revision,
      rejects_reminder_bytes: settings.rejects_reminder_bytes.revision, rejects_reminder_days: settings.rejects_reminder_days.revision,
    };
    const revisions = Object.fromEntries(Object.keys(changed).map((k) => [k, revisionOf[k]]));
    setSaving(true);
    let catalogSaved = false;
    try {
      const saved = Object.keys(changed).length ? await api.saveSettings(changed, revisions) : settings;
      catalogSaved = Object.keys(changed).length > 0;
      setSettings(saved);
      showReminder(saved);
      if (accessChanged) {
        const savedAccess = await api.saveAccess(addressList, access.revision, confirmCurrent);
        setAccess(savedAccess); setAddresses(savedAccess.hosts.join(", "));
        if (savedAccess.current_removed) {
          setMessage({kind: "ok", text: "Saved. This address is no longer allowed. Open another allowed address to continue."});
          return;
        }
      }
      setMessage({
        kind: "ok",
        text: saved.job_active ? "Saved. The running job keeps its existing settings; changes apply to future jobs." : "Saved.",
      });
      onSaved();
    } catch (e) {
      if (e instanceof ApiError && e.code === "settings_changed") {
        await load();
        setMessage({ kind: "error", text: "These settings were changed elsewhere, so nothing was saved. The current values are shown; make your change again." });
      } else if (e instanceof ApiError && e.code.startsWith("access_") || e instanceof ApiError && ["invalid_access", "current_address_removed"].includes(e.code)) {
        setGroup("access");
        setMessage({ kind: "error", text: `${catalogSaved ? "Photo settings were saved. " : ""}${e instanceof ApiError ? e.message : "Allowed addresses were not saved."}` });
      } else {
        setMessage({ kind: "error", text: `${catalogSaved ? "Photo settings were saved. Allowed-address changes could not be confirmed; reload settings before retrying. " : ""}${e instanceof ApiError ? e.message : "Settings were not saved."}` });
      }
    } finally {
      setSaving(false);
    }
  };

  const reset = () => settings && (setWorkers(String(settings.workers.value)), setRetention(String(settings.backup_retention.value)),
                                   setExts(settings.exts.value), showReminder(settings), setAddresses(access?.hosts.join(", ") ?? ""), setMessage(null), setFieldErrors({}));

  const smallImageSettings = (
    <section className={firstRun ? "notice notice-first-run" : undefined}>
        <h3>Small-image review</h3>
        {firstRun && <p id="small-required"><strong>Choose On or Off to continue.</strong> Either choice is valid; you can change it later in Settings.</p>}
        <p>A cleanup suggestion after Copy or Move, never an import restriction. Mark reviewed clears a photo’s size reminder; select unwanted photos to Reject.</p>
        <label htmlFor="settings-small-choice">Small-image reminders{firstRun && <strong> (required)</strong>}</label>
        <select id="settings-small-choice" required={firstRun} value={smallChoice} disabled={saving} aria-invalid={smallChoice !== "on" && !!fieldErrors.small} aria-describedby={[firstRun && "small-required", "small-hint", smallChoice !== "on" && fieldErrors.small && "small-error"].filter(Boolean).join(" ")} onChange={e => setSmallChoice(e.target.value)}>
          <option value="" disabled>Choose…</option><option value="on">On — suggest small images</option><option value="off">Off</option>
        </select>
        {smallChoice === "on" && <Field id="settings-small" label="Minimum shorter side (pixels)" type="number" min={1} step={1} value={smallMin} disabled={saving} onChange={e => setSmallMin(e.target.value)} error={fieldErrors.small} />}
        {smallChoice !== "on" && fieldErrors.small && <p id="small-error" className="error" role="alert">{fieldErrors.small}</p>}
        <p id="small-hint" className="muted">For example, 640 × 480 is below an 800-pixel minimum. Changing or disabling this rule updates Needs review without moving files. Photos already marked reviewed stay reviewed.</p>
      </section>
  );

  const panels: Record<Group, ReactNode> = settings ? {
    appearance: (
      <section className="appearance-settings">
        <label htmlFor="settings-theme">Color mode</label>
        <select id="settings-theme" value={theme} aria-describedby="theme-hint" onChange={event => setTheme(event.target.value as Theme)}>
          <option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option>
        </select>
        <p id="theme-hint" className="muted">Applies immediately on every screen and is remembered in this browser. System follows your device’s light/dark setting.</p>
        <label htmlFor="settings-palette">Color palette</label>
        <select id="settings-palette" value={palette} aria-describedby="palette-hint"
                onChange={(event) => setPalette(event.target.value === "warm" ? "warm" : "cool")}>
          <option value="cool">Cool neutral</option>
          <option value="warm">Warm neutral</option>
        </select>
        <p id="palette-hint" className="muted">Applies immediately and is remembered in this browser. Both palettes work in light and dark mode.</p>
      </section>
    ),
    files: (<>
      {firstRun && smallImageSettings}
      <section>
        <h3>Suspicious dates</h3>
        <Field id="settings-year" label="Earliest expected year" type="number" min={1} max={9999} step={1}
          value={minYear} disabled={saving} onChange={e => setMinYear(e.target.value)} error={fieldErrors.year}
          hint="Dates before this year are flagged for review. For example, choose 2000 to flag 1999 and earlier. Allow for older scans or family photos you want to keep." />
        <p className="muted">Starts at 1800. Dates more than one year ahead are also flagged. Saving updates warnings immediately; photo dates, Copy and Move are unchanged.</p>
      </section>
      <section>
        <h3>File types</h3>
        <p className="muted">NegativeSpace looks for these kinds of files in your source folder. Files of other types are left where they are.</p>
        <div className="ext-grid" id="settings-exts" role="group" aria-label="File types" tabIndex={-1}
             aria-invalid={!!fieldErrors.exts || undefined} aria-describedby={fieldErrors.exts ? "settings-exts-error" : undefined}>
          {offered.map((ext) => (
            <label key={ext} className={support[ext] && !support[ext].supported ? "ext unsupported" : "ext"}>
              <input type="checkbox" disabled={saving} checked={exts.includes(ext)} onChange={() => toggleExt(ext)} /> {ext}
            </label>
          ))}
        </div>
        {fieldErrors.exts && <p id="settings-exts-error" className="error">{fieldErrors.exts}</p>}
        {exts.filter((e) => support[e] && !support[e].supported).map((e) => (
          <p key={e} className="warning">{support[e].warning}</p>
        ))}
        <div className="field-inline">
          <input disabled={saving} placeholder=".ext" value={custom} onChange={(e) => setCustom(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && addCustom()} aria-label="Add a file type" />
          <button disabled={saving} onClick={addCustom}>Add file type</button>
        </div>
      </section>
      {!firstRun && smallImageSettings}
      <section>
        <h3>Rejects reminder</h3>
        <p className="muted">
          When you reject a photo, NegativeSpace moves it out of your library into a separate Rejects folder in your
          destination. It stays there, untouched, until you delete it yourself, and you can bring it back until then:
          NegativeSpace never deletes a photo. Once Rejects passes either limit below, a line on every page reminds you
          to empty it.
        </p>
        <LimitRow id="settings-reminderSize" on={sizeOn} onToggle={setSizeOn} value={sizeGb} onValue={setSizeGb}
          before="Remind me when Rejects holds at least" after="GB" min={0.1} step={0.1} disabled={saving} error={fieldErrors.reminderSize} />
        <LimitRow id="settings-reminderAge" on={ageOn} onToggle={setAgeOn} value={ageDays} onValue={setAgeDays}
          before="Remind me when a photo has been in Rejects for" after="days" min={1} step={1} disabled={saving} error={fieldErrors.reminderAge} />
      </section>
    </>),
    backups: (
      <section>
        <p className="notice">
          <strong>These are backups of NegativeSpace's catalog, not of your photos.</strong>{" "}
          The catalog is what NegativeSpace records about your photos: file information, metadata and the history of
          every change. A catalog backup cannot recreate or recover a photo. Backing up your photos is up to you; keep
          your own separate backups of them.
        </p>
        <Field id="settings-retention" label="Automatic backups to keep" type="number" min={1} step={1}
          value={retention} disabled={saving} onChange={(e) => setRetention(e.target.value)} error={fieldErrors.retention}
          hint="A backup of the catalog is taken after each job and before each change; the oldest beyond this number are deleted." />
        {!firstRun && <BackupsPanel retentionDraft={Number(retention)} />}
      </section>
    ),
    performance: (
      <section>
        <Field id="settings-workers" label="Maximum worker processes" type="number" min={1} step={1}
          value={workers} disabled={saving} onChange={(e) => setWorkers(e.target.value)} error={fieldErrors.workers}
          hint="How many photos NegativeSpace reads at once. More is faster, but leaves less of this computer for anything else." />
        <p className="notice">
          {settings.workers.limited_by
            ? <>This container may use <strong>{settings.workers.detected}</strong> of the host's {settings.workers.host} CPU
                cores, because of its {settings.workers.limited_by === "cpu_quota" ? <>CPU limit (<code>--cpus</code>)</> : <>CPU set (<code>--cpuset-cpus</code>)</>}.
                {" "}That is the default here.</>
            : <>This container may use all <strong>{settings.workers.detected}</strong> of the host's CPU cores; no CPU
                limit is set on it. That is the default here.</>}
          {" "}A value you save stays until you change it, even if the container's CPU limit changes later.
        </p>
        <p className="muted">Database queue size: {QUEUE_SIZE.toLocaleString()} items (fixed in the engine, shown for reference).</p>
      </section>
    ),
    access: access && <section aria-label="Allowed addresses">
      <h3>Allowed addresses</h3>
      <p>These are the hostnames and IP addresses you use to open NegativeSpace. Changes apply immediately and survive rebuilding or restoring the photo catalog.</p>
      <Field fullWidth id="settings-addresses" label="Additional allowed addresses" value={addresses} disabled={saving}
        onChange={e => setAddresses(e.target.value)} hint="Separate names or IP addresses with commas. Do not include http://, ports, paths or wildcards. Leave blank if you need no additional addresses." />
      <p className="muted">Current address: <strong>{access.current_host}</strong></p>
      <h3>Always allowed</h3>
      <p className="access-addresses">{access.protected_hosts.join(", ")}</p>
      <p className="muted">Local addresses and names configured through Docker cannot be removed here. For initial access or recovery on a server, set NS_ALLOWED_HOSTS in the deployment configuration and recreate the app container.</p>
      <p className="notice">This does not create DNS records, change Docker port publishing, or add sign-in. Anyone who can reach the app can use it.</p>
    </section>,
  } : { appearance: null, files: null, backups: null, performance: null, access: null };

  const status = message && <p className={message.kind === "error" ? "error" : "ok"} role={message.kind === "error" ? "alert" : "status"}>{message.text}{message.kind === "error" && <> <button onClick={load} disabled={saving}>Reload settings</button></>}</p>;

  const body = (
    <div className={firstRun ? "settings settings-page" : "settings-body"}>
      <header className="settings-head">
        <h2 id="settings-title" className={firstRun ? "brand" : undefined}>{firstRun ? <><Logo />NegativeSpace</> : "Settings"}</h2>
        {!firstRun && <button onClick={onClose} disabled={saving} aria-label="Close settings">✕</button>}
      </header>
      {!settings ? <div role="status">{message ? <><p className="error">{message.text}</p><button onClick={load}>Retry loading settings</button></> : "Loading…"}</div>
      : firstRun ? (
        <>
          {step === 0 && (
            <div className="notice notice-first-run">
              <p><strong>These are starting values, not a one-time choice.</strong></p>
              <p>
                You can change any of them at any time in the app's Settings: the <span aria-hidden="true">⚙</span> gear
                icon at the top right of every page. Check each step, then save to continue.
              </p>
            </div>
          )}
          <h3 className="settings-step" id={`${idBase}-step`}>
            <span className="muted">Step {step + 1} of {GROUPS.length}</span> {GROUPS[step].label}
          </h3>
          <div className="settings-panel" role="group" tabIndex={0} aria-labelledby={`${idBase}-step`}>{panels[group]}</div>
          {status}
          <footer className="settings-actions">
            {step > 0 && <button onClick={() => { setMessage(null); setGroup(GROUPS[step - 1].value); }} disabled={saving}>Back</button>}
            {step < GROUPS.length - 1
              ? <button className="primary" onClick={next}>Next</button>
              : <button className="primary" onClick={() => save()} disabled={saving}>{saving ? "Saving…" : "Save and continue"}</button>}
          </footer>
        </>
      ) : (
        <>
          <TabList className="settings-tabs" label="Settings" idBase={idBase} value={group} onChange={setGroup}
            tabs={GROUPS.map((g) => ({ value: g.value, label: <>{g.label}{unsaved.has(g.value) && <span className="tab-dot" role="img" aria-label="unsaved changes" />}</> }))} />
          {GROUPS.map((g) => (
            <div key={g.value} className="settings-panel" role="tabpanel" {...tabPanel(idBase, g.value, group)}>{panels[g.value]}</div>
          ))}
          <p className="notice">Processing settings apply to future jobs. Review reminders update immediately; no photos are moved.</p>
          {status}
          <footer className="settings-actions">
            <button onClick={reset} disabled={saving}>Reset</button>
            <button className="primary" onClick={() => save()} disabled={saving}>{saving ? "Saving…" : "Save settings"}</button>
          </footer>
        </>
      )}
    </div>
  );

  return <>{firstRun ? body : <Modal className="settings" labelledBy="settings-title" busy={saving} onClose={onClose}>{body}</Modal>}
    {confirmAddress && <Modal labelledBy="remove-address-title" onClose={() => setConfirmAddress(false)}>
      <h2 id="remove-address-title">Remove the address you are using?</h2>
      <p>After saving, this page and its live updates will stop working at {access?.current_host}. Open another allowed address to continue. Local and Docker-configured addresses remain available.</p>
      <div className="dialog-actions"><button autoFocus onClick={() => setConfirmAddress(false)}>Cancel</button>
        <button className="danger" onClick={() => save(true)}>Remove this address and save</button></div>
    </Modal>}
  </>;
}

// One reminder limit on one line: its on/off box, then its value, which reads as the
// rest of the sentence. The box names the limit; the value is named by the sentence.
function LimitRow({ id, on, onToggle, value, onValue, before, after, min, step, disabled, error }: {
  id: string; on: boolean; onToggle: (on: boolean) => void; value: string; onValue: (value: string) => void;
  before: string; after: string; min: number; step: number; disabled: boolean; error?: string;
}) {
  return (
    <div className="limit-row">
      <label className="checkbox-row">
        <input type="checkbox" id={`${id}-on`} disabled={disabled} checked={on} onChange={(e) => onToggle(e.target.checked)} /> {before}
      </label>
      <input id={id} type="number" min={min} step={step} value={value} disabled={disabled || !on}
             aria-label={`${before} (${after})`} aria-invalid={!!error || undefined}
             aria-describedby={error ? `${id}-error` : undefined} onChange={(e) => onValue(e.target.value)} />
      <span aria-hidden="true">{after}</span>
      {error && <p id={`${id}-error`} className="error field-error">{error}</p>}
    </div>
  );
}
