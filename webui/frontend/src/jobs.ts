// The job feed (WS /api/v1/ws/jobs) and the words the drawer uses for it.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type JobState, type Outcome, type Phase, type Run } from "./api";
import { count, plural } from "./format";

export type Connection = "connecting" | "open" | "lost";

// One socket for the page. On connect the server sends the current state, so a
// refresh or reconnect never restarts a job or loses its elapsed time (webui-spec 4.1).
export function useJobFeed(): { jobs: JobState; connection: Connection } {
  const [jobs, setJobs] = useState<JobState>({ active: null, last: null });
  const [connection, setConnection] = useState<Connection>("connecting");
  const retry = useRef(0);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let timer: number | undefined;
    let stopped = false;
    const connect = () => {
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${scheme}://${window.location.host}/api/v1/ws/jobs`);
      socket.onopen = () => {
        retry.current = 0;
        setConnection("open");
      };
      socket.onmessage = (event) => setJobs(JSON.parse(event.data) as JobState);
      socket.onclose = () => {
        if (stopped) return;
        setConnection("lost");
        retry.current = Math.min(retry.current + 1, 5);
        timer = window.setTimeout(connect, 500 * 2 ** retry.current);
      };
    };
    connect();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      socket?.close();
    };
  }, []);
  return { jobs, connection };
}

const MODE_ACTIVE: Record<string, string> = {
  INDEX: "Indexing", COPY: "Copying", MOVE: "Moving", REBUILD: "Rebuilding thumbnails",
  CHECK: "Checking the destination", RENAME: "Renaming",
};
const MODE_NAME: Record<string, string> = {
  INDEX: "Index", COPY: "Copy", MOVE: "Move", REBUILD: "Thumbnail rebuild", CHECK: "Destination check",
  RENAME: "Rename",
};
const PHASE: Record<string, string> = {
  discovering: "Looking for photos", scanning: "Reading photos", transferring: "Transferring",
  removing_duplicates: "Removing duplicate sources", rebuilding_thumbnails: "Making thumbnails",
  checking_destination: "Checking files",
};
// Outcome keys from the engine's progress counts (engine-spec 4.3), as the user reads them.
const OUTCOME: Record<string, string> = {
  eligible: "found", excluded: "other files", indexed: "new or changed", duplicates: "duplicates",
  unchanged: "unchanged", failed: "failed", Copied: "copied", Completed: "moved",
  Found_At_Destination: "already at destination", Skipped: "skipped", Failed: "failed", Cancelled: "cancelled",
  Removed_Duplicate: "duplicate sources removed", Already_Gone: "already gone", made: "made",
  already: "already present", kept: "kept", ok: "intact", missing: "missing", changed: "changed",
  unreadable: "unreadable", unknown: "not put there by NegativeSpace", Renamed: "renamed",
};

export function activeTitle(run: Run): string {
  return run.mode ? MODE_ACTIVE[run.mode] ?? run.mode : "Starting a job";
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
  "Found_At_Destination", "made", "ok", "Renamed", "already", "kept", "Skipped", "Already_Gone", "unknown",
  "Cancelled", "missing", "changed", "unreadable", "failed", "Failed"];

export function countsLine(counts: Record<string, number>): string {
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
  return [...parts, ...keys.map((k) => `${count(c[k])} ${OUTCOME[k] ?? k}`)].join(" · ");
}

// Why photos were skipped, grouped by the API from the engine's recorded reasons.
const SKIP_REASON: Record<string, string> = {
  duplicate: "duplicates: the same content is copied once",
  duplicate_original_not_selected: "duplicates whose original was not selected",
  already_copied: "copied by an earlier job",
  network_share_unconfirmed: "not attempted: a Move to a network share needs confirming",
  source_looked_empty: "not attempted: the source looked empty",
  other: "other reasons",
};

export function skipReasons(reasons: Record<string, number>): string {
  return Object.entries(reasons).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1])
    .map(([key, n]) => `${count(n)} ${SKIP_REASON[key] ?? key}`).join(", ");
}

const VERDICT: Record<string, string> = {
  success: "finished", partial: "finished with failures", failed: "failed", no_change: "had nothing to do",
  cancelled: "was cancelled", interrupted: "was interrupted", running: "is running",
};

// "Copy finished - 0 of 23 copied · 23 failed": counts lead, never a bare status
// (webui-spec 5.5).
export function summary(run: Run): { headline: string; detail: string; tone: "good" | "warn" | "bad" | "neutral" } {
  const outcome = run.outcome as Outcome;
  const name = modeName(run.mode);
  const headline = `${name} ${VERDICT[outcome.verdict] ?? outcome.verdict}`;
  const lead =
    run.mode === "COPY" && outcome.total != null
      ? `${count(outcome.counts.Copied ?? 0)} of ${plural(outcome.total, "file")} copied`
      : run.mode === "MOVE" && outcome.total != null
        ? `${count(outcome.counts.Completed ?? 0)} of ${plural(outcome.total, "file")} moved`
        : "";
  const reasons = outcome.skip_reasons ? skipReasons(outcome.skip_reasons) : "";
  const rest = countsLine(
    Object.fromEntries(Object.entries(outcome.counts).filter(([k]) =>
      !(run.mode === "COPY" && k === "Copied") && !(run.mode === "MOVE" && k === "Completed")
      && !(reasons && k === "Skipped"))),
  );
  const skipped = reasons ? `${count(outcome.counts.Skipped ?? 0)} skipped (${reasons})` : "";
  const parts = [lead, rest, skipped].filter(Boolean);
  if (outcome.run_level_issues) parts.push(`${plural(outcome.run_level_issues, "folder or file")} could not be read`);
  if (outcome.recovered_earlier_work) parts.push(`${plural(outcome.recovered_earlier_work, "earlier operation")} recovered`);
  const tone =
    outcome.verdict === "success" ? "good"
      : outcome.verdict === "no_change" ? "neutral"
        : outcome.verdict === "partial" || outcome.verdict === "cancelled" ? "warn" : "bad";
  return { headline, detail: parts.join(" · ") || "No files were processed.", tone };
}

// The finished-job banner the user dismissed, shared by every page. Kept with the
// catalog (PUT /api/v1/ui-state), so clearing the browser's data or opening another
// browser does not bring it back; the browser's copy only avoids a flash on load.
const DISMISSED_KEY = "ns.dismissedRun";

export function useDismissedRun(): [number | null, (id: number) => void] {
  const [id, setId] = useState<number | null>(() => {
    try { return Number(localStorage.getItem(DISMISSED_KEY)) || null; } catch { return null; }
  });
  const [known, setKnown] = useState(false);
  useEffect(() => {
    api.uiState().then((state) => {
      if (state.dismissed_run != null) setId((cur) => Math.max(cur ?? 0, state.dismissed_run as number));
    }, () => undefined).finally(() => setKnown(true));
  }, []);
  const dismiss = useCallback((run: number) => {
    setId(run);
    try { localStorage.setItem(DISMISSED_KEY, String(run)); } catch { /* the catalog's copy is the record */ }
    api.saveUiState({ dismissed_run: run }).catch(() => undefined);
  }, []);
  // Until the catalog has answered, treat every banner as dismissed rather than flash one.
  return [known ? id : Number.MAX_SAFE_INTEGER, dismiss];
}
