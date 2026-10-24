import { DuplicateEditNotice } from "./DuplicateEditNotice";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, type DateEditContext, type DateEditPreview, type MetadataSourceView, type Run } from "../api";
import { follow, logUrl, photoUrl, navigate, guardNavigation } from "../nav";
import { Modal } from "./ui/Modal";
import { Field } from "./ui/Field";

const targetName = (kind: string) => kind === "sidecar_xmp" ? "XMP Sidecar" : kind === "embedded_xmp" ? "Embedded XMP" : "EXIF";
const recorded = (date: DateEditContext["date"]) => !date.present ? "Not recorded" : date.value === "" ? "Empty" : date.value;

// Validate recorded calendar components without converting them to a browser timezone.
function validDate(value: string, xmp: boolean) {
  const m = /^(\d{4})(?:-(\d{2})(?:-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(Z|[+-](\d{2}):(\d{2}))?)?)?)?$/.exec(value);
  if (!m || (!xmp && !m[6])) return false;
  const [year, month, day, hour, minute, second, zoneHour, zoneMinute] = [m[1],m[2],m[3],m[4],m[5],m[6],m[8],m[9]].map(n => n === undefined ? undefined : Number(n));
  if (month !== undefined && (month < 1 || month > 12)) return false;
  const leap = year! % 4 === 0 && (year! % 100 !== 0 || year! % 400 === 0);
  const days = [31,leap ? 29 : 28,31,30,31,30,31,31,30,31,30,31];
  if (day !== undefined && (day < 1 || day > days[month! - 1])) return false;
  return (hour ?? 0) <= 23 && (minute ?? 0) <= 59 && (second ?? 0) <= 59 && (zoneHour ?? 0) <= 23 && (zoneMinute ?? 0) <= 59;
}

export function DateEditor({ photoId, donor, onClose, onSaved }: {
  photoId: number; donor?: MetadataSourceView; onClose: () => void; onSaved: () => void;
}) {
  const [context, setContext] = useState<DateEditContext | null>(null);
  const [value, setValue] = useState("");
  const [copy, setCopy] = useState(!!donor);
  const [clear, setClear] = useState(false);
  const [preview, setPreview] = useState<DateEditPreview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<Run | null>(null);
  const [discard, setDiscard] = useState(false);
  const [reload, setReload] = useState(0);
  const bypass = useRef(false);
  const leaving = useRef<string | null>(null);
  const submitted = useRef(false);
  const dirty = !!context && !submitted.current && (copy || clear || value !== (context.date.value ?? ""));
  useEffect(() => {
    let live = true;
    api.dateContext(photoId).then(data => {
      if (!live) return;
      setContext(data); setValue(donor ? String(donor.fields.date_taken ?? "") : data.date.value ?? "");
      setClear(!!donor && donor.fields.date_taken === ""); setError("");
    }, e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [photoId, donor, reload]);
  useLayoutEffect(() => {
    if (!dirty) return;
    const location = window.location.pathname + window.location.search;
    const unload = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    const move = () => {
      if (bypass.current) return true;
      leaving.current = window.location.pathname + window.location.search;
      window.history.replaceState(null, "", location);
      if (!busy) setDiscard(true); return false;
    };
    window.addEventListener("beforeunload", unload);
    const unguard = guardNavigation(move);
    return () => { window.removeEventListener("beforeunload", unload); unguard(); };
  }, [dirty, busy]);
  useEffect(() => {
    if (!run || run.id == null || !["Preparing", "Running", "Cancelling"].includes(run.status)) return;
    let live = true;
    const runId = run.id;
    const timer = setTimeout(() => api.run(runId).then(next => {
      if (!live) return;
      setRun(next); setError("");
      if (!["Preparing", "Running", "Cancelling"].includes(next.status)) onSaved();
    }, e => { if (live) { setError(e.message); setRun({ ...run }); } }), 1000);
    return () => { live = false; clearTimeout(timer); };
  }, [run, onSaved]);
  const close = () => { if (dirty) setDiscard(true); else onClose(); };
  const plan = async () => {
    if (!context) return;
    setBusy(true); setError("");
    try {
      setPreview(await api.datePreview(photoId, { capture_id: context.capture_id,
        ...(copy && donor ? { donor_id: donor.id } : { value: clear ? "" : value }) }));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const save = async () => {
    if (!preview) return;
    setBusy(true); setError("");
    try {
      const accepted = await api.saveDate(photoId, preview);
      submitted.current = true; setRun(accepted);
      if (!["Preparing", "Running", "Cancelling"].includes(accepted.status)) onSaved();
    } catch (e) { setError((e as Error).message); setPreview(null); }
    finally { setBusy(false); }
  };
  const dateError = !clear && value && context && !validDate(value,context.can_clear) ? "Enter a valid recorded date and time for this write target." : undefined;
  const change = (next: string) => { setValue(next); setCopy(false); setPreview(null); };
  return <>
    <Modal label="Edit Date taken" onClose={close} busy={busy}>
      <h2>{run?.status === "Completed" ? "Date saved" : "Edit Date taken"}</h2>
      {!context && !error && <p aria-busy="true">Loading the metadata source…</p>}
      {context && !run && <>
        <p>Write to <strong>{targetName(context.target.kind)}</strong>{context.target.create ? " — create a new sidecar containing only this date." : "."}</p>
        <p className="section-note">Current date in this source: {recorded(context.date)}. Other metadata stays unchanged.</p>
        {donor && <p className="section-note">{copy ? `Copying Date taken from ${donor.label}. This source will not become primary.` : `Started from ${donor.label}; the date below has been adjusted.`}</p>}
        <Field fullWidth type="date" label="Calendar date" min="0001-01-01" max="9999-12-31"
          value={!clear && /^\d{4}-\d{2}-\d{2}(?:T|$)/.test(value) ? value.slice(0, 10) : ""} disabled={busy || clear || !!preview}
          hint="Choose a day. The recorded time and time zone stay unchanged, including fractions of a second. Use Date taken below to change them or enter a partial date."
          onChange={e => {
            // Work with the recorded text, never a Date that converts through a timezone.
            const day = e.target.value;
            if (day) change(day + (value.includes("T") ? value.slice(value.indexOf("T")) : ""));
          }} />
        <Field fullWidth label="Date taken" error={dateError} value={clear ? "" : value} maxLength={128} disabled={busy || clear || !!preview}
          hint="Use YYYY-MM-DDTHH:MM:SS, with any recorded fraction and timezone offset. Example: 2020-06-15T14:30:00.123+02:00. No timezone is assumed."
          onChange={e => change(e.target.value)} />
        <label className="checkbox-row"><input type="checkbox" checked={clear} disabled={busy || !!preview || !context.can_clear}
          onChange={e => { setClear(e.target.checked); setCopy(false); setPreview(null); }} />Explicitly clear Date taken</label>
        {context.can_clear && !context.date.present && <p className="section-note">This XMP has no date. Another source may still supply the filing date. Explicitly clearing Date taken prevents that fallback and files the photo under Undated.</p>}
        {!context.can_clear && <p className="section-note">An explicitly empty date is supported only in XMP. The app will not switch your primary source automatically.</p>}
        <p className="section-note">Changing the filing date may move this photo and its sidecar to another folder. An explicit clear files it under Undated.</p>
        {preview && <section aria-label="Date change preview">
          <h3>{preview.no_change ? "No changes needed" : "Confirm date and location"}</h3>
          <dl><dt>Before</dt><dd>{recorded(preview.before)}</dd><dt>After</dt><dd>{preview.after === "" ? "Explicitly cleared" : preview.after}</dd>
            <dt>Current location</dt><dd><code>{preview.filing.current}</code></dd>
            <dt>Resulting location</dt><dd><code>{preview.duplicate?.path ?? preview.filing.proposed}</code></dd></dl>
          {preview.date_warning && !preview.no_change && <p className="warning" role="status"><strong>This date looks unusual.</strong> {preview.date_warning} You can still save it if it is correct.</p>}
          {!preview.duplicate && preview.filing.collision_renamed && <p>The filename has been numbered to avoid an existing file. Nothing will be overwritten.</p>}
          {preview.duplicate && <DuplicateEditNotice duplicate={preview.duplicate}/>}
          <p>{preview.no_change ? "The date and filing location already match. Nothing will be written." : "Only Date taken and its time details are saved. Files and naming conflicts are checked before any changes."}</p>
        </section>}
        <div className="settings-actions">
          <button disabled={busy} onClick={close}>Cancel</button>
          {preview ? <><button disabled={busy} onClick={() => setPreview(null)}>Back to edit</button>
            <button className="primary" disabled={busy || preview.no_change} onClick={() => void save()}>{busy ? "Submitting…" : preview.duplicate ? "Save and keep existing photo" : preview.filing.change ? "Save date and move file" : "Save date"}</button></>
          : <button className="primary" disabled={busy || !!dateError || (!clear && !value.trim())} onClick={() => void plan()}>{busy ? "Checking…" : "Preview change"}</button>}
        </div>
      </>}
      {run && <>
        <section role="status">
          {run.status === "Completed" ? <p>Date taken was saved to {context ? targetName(context.target.kind) : "the primary metadata source"}.</p>
            : <p>Metadata job #{run.id}: {run.status}</p>}
          {run.status === "Completed" && preview?.duplicate && <p>The existing photo was kept. <a href={photoUrl(preview.duplicate.photo_id)} onClick={follow}>Open {preview.duplicate.filename}</a></p>}
          {run.status === "Failed" && <p>The save did not complete. Review the job details and any file issue before starting another edit.</p>}
        </section>
        <footer className="settings-actions">
          <a href={logUrl({run:run.id,photo:photoId})} onClick={follow}>View job details</a>
          <button className="primary" onClick={onClose}>Close</button>
        </footer>
      </>}
      {error && <p className="error" role="alert">{error}</p>}
      {!context && error && <div className="settings-actions"><button onClick={() => setReload(n => n+1)}>Reload editor</button><button onClick={onClose}>Close</button></div>}
    </Modal>
    {discard && <Modal label="Discard your unsaved changes?" onClose={() => { leaving.current=null; setDiscard(false); }} role="alertdialog">
      <h2>Discard your unsaved changes?</h2>
      <div className="settings-actions"><button onClick={() => { leaving.current=null; setDiscard(false); }}>Keep editing</button>
        <button onClick={() => { bypass.current=true; onClose(); if (leaving.current) navigate(leaving.current,true); }}>Discard</button></div>
    </Modal>}
  </>;
}
