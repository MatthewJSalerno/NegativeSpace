// The job feed (WS /api/v1/ws/jobs) and the words the drawer uses for it.
import { createContext, createElement, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, type JobState, type Outcome, type Phase, type Run } from "./api";
import { count, plural } from "./format";

export type Connection = "connecting" | "open" | "lost";

// One socket for the page. On connect the server sends the current state, so a
// refresh or reconnect never restarts a job or loses its elapsed time (webui-spec 4.1).
interface JobFeed { jobs: JobState; connection: Connection }
const JobFeedContext = createContext<JobFeed | null>(null);

// Establish a baseline before page queries start. Otherwise the initial last-job
// snapshot looks like a newly finished job and repeats every expensive request.
// The provider survives navigation; it caches job state, never gallery/query data.
export function JobFeedProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<JobState | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let socket: WebSocket | null = null;
    let retryTimer: number | undefined;
    let fallbackTimer: number | undefined;
    let stopped = false, received = false, retry = 0;
    const fallback = () => {
      if (stopped || received) return;
      api.jobState().then((state) => {
        if (!stopped && !received) { setJobs(state); setError(false); }
      }, () => { if (!stopped && !received) setError(true); });
    };
    const connect = () => {
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${scheme}://${window.location.host}/api/v1/ws/jobs`);
      socket.onopen = () => { retry = 0; setConnection("open"); };
      socket.onmessage = (event) => {
        if (stopped) return;
        received = true;
        setJobs(JSON.parse(event.data) as JobState); setError(false);
      };
      socket.onclose = () => {
        if (stopped) return;
        setConnection("lost");
        retry = Math.min(retry + 1, 5);
        retryTimer = window.setTimeout(connect, 500 * 2 ** retry);
      };
    };
    connect();
    // A proxy without WebSocket support must not prevent browsing. The drawer
    // still reports the lost live connection; a later snapshot catches up.
    fallbackTimer = window.setTimeout(fallback, 2000);
    return () => {
      stopped = true;
      window.clearTimeout(retryTimer); window.clearTimeout(fallbackTimer);
      socket?.close();
    };
  }, [attempt]);
  if (!jobs) return createElement("div", { className: "center-page", role: "status" },
    error ? "Job state could not be loaded. " : "Loading…",
    error && createElement("button", { onClick: () => { setError(false); setAttempt(n => n + 1); } }, "Retry"));
  return createElement(JobFeedContext.Provider, { value: { jobs, connection } }, children);
}

export function useJobFeed(): JobFeed {
  const feed = useContext(JobFeedContext);
  if (!feed) throw new Error("JobFeedProvider is required");
  return feed;
}

export function useJobCompletion(onFinished: () => void) {
  const { jobs } = useJobFeed();
  const key = jobs.last && !["Preparing", "Running", "Cancelling"].includes(jobs.last.status)
    ? `${jobs.last.id}:${jobs.last.status}` : null;
  const previous = useRef(key);
  const callback = useRef(onFinished); callback.current = onFinished;
  useEffect(() => {
    if (key == null) return;
    if (previous.current !== key) callback.current();
    previous.current = key;
  }, [key]);
}

const MODE_NAME: Record<string, string> = {
  INDEX: "Index", COPY: "Copy", MOVE: "Move", REBUILD: "Thumbnail rebuild", CHECK: "Destination check",
  SIMILARITY: "Similarity recovery", RENAME: "Rename", REJECT: "Reject", RETURN: "Return to library",
};
const PHASE: Record<string, string> = {
  discovering: "Looking for photos", scanning: "Reading photos", transferring: "Transferring",
  removing_duplicates: "Removing duplicate sources", rebuilding_thumbnails: "Making thumbnails",
  checking_destination: "Checking files", matching: "Comparing photos",
};
// Outcome keys from the engine's progress counts (engine-spec 4.3), as the user reads them.
const OUTCOME: Record<string, string> = {
  eligible: "found", excluded: "other files", indexed: "new or changed", duplicates: "duplicates",
  unchanged: "unchanged", failed: "failed", Copied: "copied", Completed: "moved",
  Found_At_Destination: "already at destination", Skipped: "skipped", Failed: "failed", Cancelled: "cancelled",
  Removed_Duplicate: "duplicate sources removed", Already_Gone: "already gone", made: "made",
  Compared: "hashes compared", already: "already present", kept: "kept", ok: "intact", missing: "missing", changed: "changed",
  unreadable: "unreadable", unknown: "not put there by NegativeSpace", Renamed: "renamed",
  Rejected: "in Rejects", Rejected_Copied: "in Rejects, original kept", Returned: "returned to the library",
};

export function activeTitle(run: Run): string {
  return run.mode ? `${jobLabel(run.id, run.mode)} ${run.status === "Cancelling" ? "cancelling" : run.status === "Preparing" ? "preparing" : run.status === "Interrupted" ? "interrupted" : "running"}` : "Starting a job";
}

// Jobs that act on photos, whose photos the Library can show (webui-spec 2, after a job).
export function showsPhotos(run: Run): boolean {
  return ["COPY", "MOVE", "REJECT", "RETURN", "RENAME"].includes(run.mode ?? "") && (run.outcome?.total ?? 0) > 0;
}

export function jobLabel(id: number | null | undefined, mode: string | null): string {
  return id == null ? modeName(mode) : `Job #${id} · ${modeName(mode)}`;
}

export function modeName(mode: string | null): string {
  return mode ? MODE_NAME[mode] ?? mode : "Job";
}

export function currentPhase(run: Run): Phase | null {
  const phases = run.progress ?? [];
  return phases.length ? phases[phases.length - 1] : null;
}

export function phaseLabel(phase: Phase): string {
  return PHASE[phase.phase] ?? phase.phase;
}

// Successes first, then non-actions, then problems.
const ORDER = ["eligible", "excluded", "indexed", "unchanged", "Copied", "Completed", "Removed_Duplicate",
  "Found_At_Destination", "Rejected", "Rejected_Copied", "Returned", "made", "ok", "Renamed", "already", "kept", "Skipped", "Already_Gone", "unknown",
  "Cancelled", "missing", "changed", "unreadable", "failed", "Failed"];

export function countsLine(counts: Record<string, number>, mode?: string | null): string {
  const c = { ...counts };
  const parts: string[] = [];
  // The engine counts a scan's new files and its duplicates separately; they are
  // one figure with duplicates as a subset, never two added together (webui-spec 4.1).
  if (c.indexed || c.duplicates) {
    const all = (c.indexed ?? 0) + (c.duplicates ?? 0);
    parts.push(`${count(all)} new or changed${c.duplicates ? `, including ${plural(c.duplicates, "duplicate")}` : ""}`);
    delete c.indexed;
    delete c.duplicates;
  }
  const keys = Object.keys(c).filter((k) => c[k] > 0)
    .sort((a, b) => (ORDER.indexOf(a) + 1 || 99) - (ORDER.indexOf(b) + 1 || 99));
  // In a Move, Copied is a file whose original could not be deleted.
  const label = (k: string) => (mode === "MOVE" && k === "Copied" ? "copied only" : OUTCOME[k] ?? k);
  return [...parts, ...keys.map((k) => `${count(c[k])} ${label(k)}`)].join(" · ");
}

// Why photos were skipped, grouped by the API from the engine's recorded reasons.
const SKIP_REASON: Record<string, string> = {
  duplicate: "duplicates: the same content is copied once",
  duplicate_original_not_selected: "duplicates whose original was not selected",
  already_copied: "copied by an earlier job",
  already_rejected: "already rejected: kept out of the library",
  already_in_rejects: "already in Rejects",
  not_organized: "not organized yet",
  copy_follows_original: "copies that follow their original",
  already_in_library: "already in the library",
  not_in_rejects: "not in Rejects",
  rejects_emptied: "emptied from Rejects",
  network_share_unconfirmed: "not attempted: a Move to a network share needs confirming",
  source_looked_empty: "not attempted: the source looked empty",
  other: "other reasons",
};

export function skipReasons(reasons: Record<string, number>): string {
  return Object.entries(reasons).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1])
    .map(([key, n]) => `${count(n)} ${SKIP_REASON[key] ?? key}`).join(", ");
}

const VERDICT: Record<string, string> = {
  success: "finished", partial: "finished with failures", originals_kept: "finished, originals kept",
  none_succeeded: "finished, nothing succeeded", stopped: "stopped by an error", no_change: "had nothing to do",
  cancelled: "was cancelled", interrupted: "was interrupted", running: "is running",
};

// "Copy finished - 0 of 23 copied · 23 failed": counts lead, never a bare status
// (webui-spec 5.5).
// `numbered` names the job ("Job #8 · Copy finished"), for the finished banner: beside a job's
// photos it may describe a different job than the one shown (webui-spec 2, after a job).
export function summary(run: Run, numbered = true): { headline: string; detail: string; tone: "good" | "warn" | "bad" | "neutral" } {
  const outcome = run.outcome as Outcome;
  const name = numbered && run.id != null ? jobLabel(run.id, run.mode) : modeName(run.mode);
  const headline = `${name} ${VERDICT[outcome.verdict] ?? outcome.verdict}`;
  const lead =
    run.mode === "COPY" && outcome.total != null
      ? `${count(outcome.counts.Copied ?? 0)} of ${plural(outcome.total, "file")} copied`
      : run.mode === "MOVE" && outcome.total != null
        ? `${count(outcome.counts.Completed ?? 0)} of ${plural(outcome.total, "file")} moved`
        : run.mode === "REJECT" && outcome.total != null
          ? `${count(outcome.counts.Rejected ?? 0)} of ${plural(outcome.total, "photo")} moved to Rejects`
          : run.mode === "RETURN" && outcome.total != null
            ? `${count(outcome.counts.Returned ?? 0)} of ${plural(outcome.total, "photo")} returned to the library`
            : "";
  const reasons = outcome.skip_reasons ? skipReasons(outcome.skip_reasons) : "";
  const rest = countsLine(
    Object.fromEntries(Object.entries(outcome.counts).filter(([k]) =>
      !(run.mode === "COPY" && k === "Copied") && !(run.mode === "MOVE" && (k === "Completed" || k === "Copied"))
      && !(run.mode === "REJECT" && k === "Rejected") && !(run.mode === "RETURN" && k === "Returned")
      && !(run.mode === "MOVE" && k === "Rejected_Copied")
      && !(reasons && k === "Skipped"))),
  );
  // A Move that could not delete an original copied it: said as such, never as moved.
  const kept = run.mode === "MOVE" && outcome.copied_only
    ? `${count(outcome.copied_only)} copied only: the original could not be removed` : "";
  const skipped = reasons ? `${count(outcome.counts.Skipped ?? 0)} skipped (${reasons})` : "";
  const parts = [lead, kept, rest, skipped].filter(Boolean);
  if (outcome.run_level_issues) parts.push(`${plural(outcome.run_level_issues, "folder or file")} could not be read`);
  if (outcome.recovered_earlier_work) parts.push(`${plural(outcome.recovered_earlier_work, "earlier operation")} recovered`);
  const tone =
    outcome.verdict === "success" ? "good"
      : outcome.verdict === "no_change" ? "neutral"
        : outcome.verdict === "partial" || outcome.verdict === "cancelled" || outcome.verdict === "originals_kept"
          ? "warn" : "bad";
  return { headline, detail: parts.join(" · ") || "No files were processed.", tone };
}

// The hover text for a run's problems: why originals were kept and why files failed,
// each reason with its count, most first.
export function reasonsText(outcome: Outcome | null | undefined): string | null {
  const block = (title: string, all: Record<string, number> | undefined) => {
    const reasons = Object.entries(all ?? {}).sort((a, b) => b[1] - a[1]);
    if (reasons.length === 0) return null;
    const shown = reasons.slice(0, 6).map(([r, n]) => `${r}: ${count(n)}`);
    if (reasons.length > 6) shown.push(`and ${reasons.length - 6} more reasons (see the log)`);
    return `${title}\n${shown.join("\n")}`;
  };
  const blocks = [block("Why originals were kept:", outcome?.kept_reasons), block("Why they failed:", outcome?.failure_reasons)]
    .filter(Boolean);
  return blocks.length ? blocks.join("\n\n") : null;
}
