import { useEffect, useState } from "react";
import { api, ApiError, type PreviewsFreed, type Run, type ThumbnailCache } from "../api";
import { bytes, count, plural } from "../format";
import { currentPhase, jobLabel, phaseLabel, summary, useJobCompletion, useJobFeed } from "../jobs";

// The thumbnail cache (webui-spec 4.2.1), in Settings › Performance: its size by kind,
// Free up for detail previews, and Repair or Rebuild all for grid thumbnails. The two
// kinds are managed separately: losing previews costs nothing, losing grid thumbnails
// blanks the gallery until a rebuild. Free up acts and reports; a rebuild is a job,
// followed here through the shared job feed, with no time estimate.
export function ThumbnailsPanel() {
  const { jobs } = useJobFeed();
  const [data, setData] = useState<ThumbnailCache | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [started, setStarted] = useState<Run | null>(null);
  const [message, setMessage] = useState<{ kind: "error" | "ok" | "warning"; text: string } | null>(null);

  const load = () => api.thumbnails().then((d) => { setData(d); setLoadError(null); },
    (e) => setLoadError(e instanceof ApiError ? e.message : "The thumbnail cache could not be read."));
  useEffect(() => { load(); }, []);
  // A finished job may have made thumbnails (Index, Copy, a rebuild): show the new sizes.
  useJobCompletion(() => { void load(); });

  const running = jobs.active && jobs.active.presented_status !== "Interrupted" ? jobs.active : null;
  const rebuilding = running && running.mode === "REBUILD" ? running : null;
  const finished = started && jobs.last?.id === started.id && !running ? jobs.last : null;

  const freeUp = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const freed: PreviewsFreed = await api.clearPreviews();
      setMessage(freed.not_removed
        ? { kind: "warning", text: `Freed ${bytes(freed.bytes_freed)} from ${plural(freed.removed, "detail preview")}. `
            + `${plural(freed.not_removed, "preview")} could not be removed: check that the thumbnail cache folder `
            + "is writable, then free up again." }
        : { kind: "ok", text: freed.removed
            ? `Freed ${bytes(freed.bytes_freed)} from ${plural(freed.removed, "detail preview")}.`
            : "There were no detail previews to remove." });
    } catch (e) {
      setMessage({ kind: "error", text: e instanceof ApiError ? e.message : "Detail previews could not be removed." });
    } finally {
      setBusy(false);
      void load();
    }
  };

  const rebuild = async (scope: "missing" | "all") => {
    setBusy(true);
    setMessage(null);
    try {
      setStarted(await api.rebuildThumbnails(scope));
    } catch (e) {
      setMessage({ kind: "error", text: e instanceof ApiError ? e.message : "The rebuild could not be started." });
    } finally {
      setBusy(false);
    }
  };

  if (!data) return loadError
    ? <div className="thumbnails"><p className="error" role="alert">{loadError}</p><button onClick={load}>Retry</button></div>
    : <p className="muted">Loading the thumbnail cache…</p>;

  const phase = rebuilding && currentPhase(rebuilding);
  const outcome = finished && summary(finished);
  return (
    <section className="thumbnails" aria-labelledby="thumbnails-title">
      <h3 id="thumbnails-title">Thumbnail cache — {bytes(data.grid.bytes + data.previews.bytes)}</h3>
      <p>Grid thumbnails · {bytes(data.grid.bytes)} · {plural(data.grid.photos, "photo")}</p>
      <p>Detail previews · {bytes(data.previews.bytes)} · {plural(data.previews.photos, "photo")} opened</p>

      <div className="panel-actions">
        <button onClick={freeUp} disabled={busy || data.previews.photos === 0}>
          Free up previews
        </button>
        {/* Both explanations share one space, so freeing previews never resizes the row. */}
        <div className="muted stable-content">
          <div aria-hidden={!data.previews.photos || undefined}>
            Removes <strong>{bytes(data.previews.bytes)}</strong> of detail previews. They are recreated automatically the next time
            you open a photo, so nothing is lost.</div>
          <div aria-hidden={!!data.previews.photos || undefined}>No detail previews are stored.</div>
        </div>
        <button onClick={() => rebuild("missing")} disabled={busy || !!running}>Repair grid thumbnails</button>
        <span className="muted">Makes the ones that are missing. Quick when little is missing.</span>
        <button onClick={() => rebuild("all")} disabled={busy || !!running}>Rebuild all grid thumbnails</button>
        <span className="muted">Regenerates every one from your photos. How long this takes depends on the size of your library.</span>
      </div>

      <div className="thumbnails-status" role="status">
        {rebuilding
          ? <p>{jobLabel(rebuilding.id, rebuilding.mode)} is running{phase
              ? `: ${phaseLabel(phase)}, ${count(phase.done)}${phase.total != null ? ` of ${count(phase.total)}` : ""}` : ""}.
              {" "}You can close Settings; it also shows at the top of the page.</p>
          : running
            ? <p className="muted">A job is running. Repair and rebuild become available when it finishes.</p>
            : outcome
              ? <p className={outcome.tone === "bad" ? "error" : outcome.tone === "warn" ? "warning" : "ok"}>
                  <strong>{outcome.headline}</strong>{outcome.detail ? <> {outcome.detail}</> : null}</p>
              : started
                ? <p>{jobLabel(started.id, started.mode)} has started.</p>
                : null}
        {message && message.kind !== "error" && <p className={message.kind}>{message.text}</p>}
      </div>
      {message?.kind === "error" && <p className="error" role="alert">{message.text}</p>}
    </section>
  );
}
