// Earlier versions of edited Library photos (engine-spec 10, "Earlier versions: the agreed
// behaviour"): the hold's reason, the full recorded change list, the answers, and the
// links between the two photos. Answers change no files.
import { useEffect, useState } from "react";
import { api, type PhotoVersions, type VersionBadge, type VersionChange, type VersionFiling, type VersionState } from "../api";
import { instant, isFallbackDate, photoDate } from "../format";
import { jobLabel } from "../jobs";
import { follow, logUrl, photoUrl } from "../nav";
import { LABELS, display } from "./metadataFields";
import { Modal } from "./ui/Modal";

const SOURCE: Record<string, string> = { exif: "EXIF", embedded_xmp: "Embedded XMP" };
const ORIENTATION: Record<string, string> = {
  "1": "Upright", "2": "Mirrored", "3": "Turned 180°", "4": "Mirrored and turned 180°",
  "5": "Mirrored and turned 90° counterclockwise", "6": "Turned 90° clockwise",
  "7": "Mirrored and turned 90° clockwise", "8": "Turned 90° counterclockwise",
};

/** The card badge text for a photo's version links, or null when it has none. */
export function versionBadge(version: VersionBadge | null | undefined): string | null {
  if (!version) return null;
  if (version.version_of != null) return version.state === "waiting" ? "Earlier version · waiting for your answer"
    : version.state === "not_kept" ? "Earlier version · not kept" : "Earlier version";
  return version.earlier_versions > 0 ? "Has an earlier version" : null;
}

function value(field: string, recorded: unknown) {
  if (recorded == null) return "Not recorded";
  if (field === "orientation" && ORIENTATION[String(recorded)]) return ORIENTATION[String(recorded)];
  return display({ [field]: recorded }, field);
}

// The same action-and-outcome names History and Logs use.
function changeLabel(change: VersionChange) {
  const fields = new Set(change.fields.map(f => f.field));
  if (fields.size === 1 && fields.has("date_taken")) return "Date saved";
  if (fields.size === 1 && fields.has("orientation")) return "Rotation saved";
  return "Metadata saved";
}

function Changes({ changes, photoId }: { changes: VersionChange[]; photoId: number }) {
  return <ol className="version-changes">
    {changes.map(change => {
      const sources = [...new Set(change.fields.map(f => SOURCE[f.source] ?? f.source))];
      return <li key={change.change_id}>
        <strong>{changeLabel(change)}</strong> · {instant(change.at)} ·{" "}
        <a href={logUrl({ run: change.run_id, photo: photoId })} onClick={follow}>{jobLabel(change.run_id, change.mode)}</a>
        <table className="review-metadata-table"><thead><tr><th>Detail</th><th>Before</th><th>After</th></tr></thead><tbody>
          {change.fields.map(f => <tr key={`${f.source}:${f.field}`}><th>{LABELS[f.field] ?? f.field.replaceAll("_", " ")}</th>
            <td>{value(f.field, f.before)}</td><td>{value(f.field, f.after)}</td></tr>)}
          {change.tags.map(t => <tr key={t.tag}><th><code>{t.tag}</code></th>
            <td>{t.before == null ? "Not recorded" : String(t.before)}</td><td>{t.after == null ? "Not recorded" : String(t.after)}</td></tr>)}
        </tbody></table>
        {sources.length > 0 && <p className="section-note">Details from: {sources.join(" · ")}</p>}
      </li>;
    })}
  </ol>;
}

// Where a photo files, from its recorded filing date, worded as the Inspector words the
// source and the Undated fallback.
function filedUnder(filing: VersionFiling) {
  if (!filing.date_taken) return <>a date that is not recorded</>;
  if (isFallbackDate(filing.date_source)) return <><strong>Undated</strong> ({filing.date_taken.slice(0, 4)}, the file's modification year)</>;
  const source = filing.date_source === "exif" ? "EXIF" : filing.date_source === "xmp" ? "XMP" : null;
  return <><strong>{photoDate(filing.date_taken)}</strong>{source ? ` (filing date from ${source})` : ""}</>;
}

const ANSWER: Record<VersionState, string> = {
  waiting: "Waiting for your answer", not_kept: "Not kept", keep_separate: "Kept as its own photo",
};

export function EarlierVersions({ photoId, version, jobRunning, refreshKey }: {
  photoId: number; version: VersionBadge; jobRunning: boolean; refreshKey: number;
}) {
  const [data, setData] = useState<PhotoVersions | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  useEffect(() => {
    let live = true;
    setError("");
    api.versions(photoId).then(d => { if (live) setData(d); },
      e => { if (live) setError(e instanceof Error ? e.message : "The earlier-version details could not be loaded."); });
    return () => { live = false; };
  }, [photoId, refreshKey, version.state, version.waiting]);

  const answer = async (choice: "not_kept" | "keep_separate") => {
    if (!data) return;
    setBusy(true); setError("");
    const requestId = Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, "0")).join("");
    try {
      setData(await api.answerVersion(photoId, choice, data.revision, requestId));
      setConfirming(false);
      window.dispatchEvent(new Event("ns-review-changed"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "The answer was not confirmed. Reload the photo before retrying.");
    } finally { setBusy(false); }
  };

  if (!data) return error ? <p className="error" role="alert">{error}</p> : null;
  const earlier = data.earlier_version;
  const waitTitle = jobRunning ? "Wait for the running job to finish." : undefined;

  return <>
    {earlier && earlier.state != null && <section className="notice" aria-label="Earlier version">
      <strong>{earlier.state === "waiting" ? "Earlier version of a Library photo" : `Earlier version · ${ANSWER[earlier.state].toLowerCase()}`}</strong>
      <p>This file is how <a href={photoUrl(earlier.version_of.id)} onClick={follow}>{earlier.version_of.filename}</a> in
        {" "}{earlier.version_of.location} looked before it was edited in NegativeSpace. It is not identical to anything
        organized, so Copy and Move {earlier.state === "keep_separate" ? "treat it as a photo of its own." : "leave it in the source."}</p>
      {earlier.same_picture && <p>Only the photo's details changed; the picture is the same.</p>}
      <p>Changes since this version:</p>
      <Changes changes={earlier.changes} photoId={earlier.version_of.id} />
      {earlier.state === "not_kept" && <p>It stays in the source untouched. NegativeSpace never removes it.</p>}
      {earlier.state === "keep_separate" && earlier.answerable && <p>Your next Copy or Move organizes it as its own photo, filed by its own details.</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {earlier.answerable && <div className="settings-actions">
        {earlier.state !== "not_kept" && <button className="photo-action" disabled={busy || jobRunning} title={waitTitle}
          onClick={() => void answer("not_kept")}>Don't keep it</button>}
        {earlier.state !== "keep_separate" && <button className="photo-action" disabled={busy || jobRunning} title={waitTitle}
          onClick={() => setConfirming(true)}>{earlier.state === "not_kept" ? "Keep it after all…" : "Keep it as its own photo…"}</button>}
        <a href={logUrl({ photo: earlier.version_of.id })} onClick={follow}>View the edited photo's logs</a>
      </div>}
      {earlier.answers.length > 0 && <details><summary>Your answers</summary><ul>
        {earlier.answers.map((a, i) => <li key={i}>{ANSWER[a.answer]} · {instant(a.at)}</li>)}
      </ul></details>}
    </section>}
    {earlier && earlier.state == null && <p className="section-note">Earlier version of{" "}
      <a href={photoUrl(earlier.version_of.id)} onClick={follow}>{earlier.version_of.filename}</a>, kept as its own photo.</p>}
    {data.earlier_versions.length > 0 && <p className="section-note">
      <strong>Has an earlier version:</strong>{" "}
      {data.earlier_versions.map((v, i) => <span key={v.id}>{i > 0 && ", "}
        <a href={photoUrl(v.id)} onClick={follow}>{v.filename}</a> ({v.location}{v.state ? ` · ${ANSWER[v.state].toLowerCase()}` : ""})</span>)}
    </p>}
    {confirming && earlier && <Modal label="Keep it as its own photo" onClose={() => setConfirming(false)} busy={busy}>
      <h2>Keep it as its own photo?</h2>
      <p>Your next Copy or Move organizes this earlier version as a separate photo, filed by its own details,
        under {filedUnder(earlier.filing)}.</p>
      <p>{earlier.version_of.filename} in {earlier.version_of.location} is filed under {filedUnder(earlier.version_of.filing)}
        {" "}and is not changed. The two stay linked as versions.</p>
      {error && <p className="error" role="alert">{error}</p>}
      <footer className="settings-actions"><button disabled={busy} onClick={() => setConfirming(false)}>Cancel</button>
        <button className="primary" disabled={busy || jobRunning} title={waitTitle} onClick={() => void answer("keep_separate")}>Keep it as its own photo</button></footer>
    </Modal>}
  </>;
}
