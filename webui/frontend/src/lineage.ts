import type { Lineage, LineageFile, LineageOperation } from "./api";
import { operationLabel } from "./jobs";

export const LANES = ["Source", "Identical copies", "Library", "Rejects"];
export const RETRY_MODE: Record<string, "index" | "copy" | "move"> = { INDEX: "index", COPY: "copy", MOVE: "move" };
const LABELS: Record<string, string> = {
  Pending: "Indexed", Duplicate: "Indexed as an identical copy", Processing: "Started",
  Completed: "Moved and verified", Copied: "Copied and verified", Copied_Only: "Copied; original kept",
  Failed: "Failed", Removed_Duplicate: "Identical source removed; existing destination retained",
  Found_At_Destination: "Existing destination retained", Skipped: "Skipped", Cancelled: "Cancelled",
  Renamed: "Renamed", Rejected: "Moved to Rejects", Rejected_Copied: "Moved to Rejects; original kept",
  Returned: "Returned to Library",
};
export const actionLabel = (op: LineageOperation) => operationLabel(op, LABELS[op.status] ?? op.status);
export const shortJob = (op: LineageOperation) => `${({ INDEX: "Index", COPY: "Copy", MOVE: "Move", REJECT: "Reject", RETURN: "Return", RENAME: "Rename", METADATA: "Metadata", CHECK: "Check" } as Record<string, string>)[op.mode ?? ""] ?? op.mode ?? "Job"} #${op.run_id}`;
// Compare immutable discovery evidence, never the current photo's edited hash.
export function sourceLanes(tree: Lineage): Map<number, number> {
  const original = tree.files.find(file => file.photo_id === tree.photo_id)?.indexed_sha1;
  const duplicateDiscoveries = new Set<number>();
  const files = new Map(tree.files.map(file => [file.file_id, file]));
  for (const op of tree.operations) {
    if (op.mode !== "INDEX" || op.status !== "Duplicate") continue;
    for (const link of op.files) {
      if (files.get(link.file_id)?.created_run_id === op.run_id) duplicateDiscoveries.add(link.file_id);
    }
  }
  return new Map(tree.files.map(file => [file.file_id,
    file.photo_id !== tree.photo_id && ((file.indexed_sha1 && file.indexed_sha1 === original) || duplicateDiscoveries.has(file.file_id)) ? 1 : 0]));
}
export interface TimelineEvent {
  key: string;
  operations: LineageOperation[];
  discoveries: LineageFile[];
  kind: string;
}

export function timelineEvents(tree: Lineage): TimelineEvent[] {
  const files = new Map(tree.files.map(file => [file.file_id, file]));
  const discovered = new Set<number>();
  const events: TimelineEvent[] = [];
  const indexes = new Map<string, TimelineEvent>();
  for (const op of tree.operations) {
    const fresh = op.mode === "INDEX" ? op.files.flatMap(link => {
      const file = files.get(link.file_id);
      if (!file || file.origin_kind !== "indexed" || file.created_run_id !== op.run_id || discovered.has(file.file_id)) return [];
      discovered.add(file.file_id);
      return [file];
    }) : [];
    // A single discovery row retains each operation and its file-specific log link.
    // Changed files indexed later remain separate events, never new arrivals.
    const discoveryKey = `${op.run_id}:${fresh[0]?.indexed_sha1 ?? op.id}`;
    const existing = fresh.length ? indexes.get(discoveryKey) : undefined;
    if (existing) { existing.operations.push(op); existing.discoveries.push(...fresh); continue; }
    const event = { key: String(op.id), operations: [op], discoveries: fresh,
      kind: fresh.length ? "discovery" : `${op.mode}:${op.status}:${op.action}:${op.recovery}` };
    events.push(event);
    if (fresh.length) indexes.set(discoveryKey, event);
  }
  return events;
}

export function eventGroups(events: TimelineEvent[], splits: ReadonlySet<number> = new Set()): TimelineEvent[][] {
  const groups: TimelineEvent[][] = [];
  // Failures, recovery and a version split must not disappear behind a generic
  // successful-action group.
  const alone = (event: TimelineEvent) => event.operations.some(op => op.status === "Failed" || op.recovery || splits.has(op.id));
  for (const event of events) {
    const last = groups.at(-1);
    if (last && last[0].kind === event.kind && !alone(event) && !alone(last.at(-1)!)) last.push(event);
    else groups.push([event]);
  }
  return groups.flatMap(group => group.length >= 3 ? [group] : group.map(event => [event]));
}

export function recordedNow(tree: Lineage): string {
  const present = tree.files.filter(file => file.presence === "present");
  const places = [...new Set(present.filter(file => file.role === "destination").map(file => file.place === "library" ? "Library" : file.place === "rejects" ? "Rejects" : "the destination (place not recorded)"))];
  const sources = present.filter(file => file.role === "source").length;
  const missing = tree.files.filter(file => file.presence === "missing").length;
  const uncertain = tree.files.filter(file => file.presence == null).length;
  return `${places.length ? `In ${places.join(" and ")}` : sources ? "In the source" : "No file recorded as present"}. ${sources} ${sources === 1 ? "original remains" : "originals remain"} in the source.${missing ? ` ${missing} ${missing === 1 ? "file is" : "files are"} recorded missing.` : ""}${uncertain ? ` Presence is unknown for ${uncertain} files.` : ""}`;
}

export function historySummary(tree: Lineage, events: TimelineEvent[]): string {
  const discoveries = events.filter(event => event.discoveries.length);
  const indexCount = new Set(discoveries.map(event => event.operations[0].run_id)).size;
  const found = discoveries.reduce((n, event) => n + event.discoveries.length, 0);
  const day = (op: LineageOperation) => new Date(op.timestamp).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  const first = discoveries[0]?.operations[0], last = discoveries.at(-1)?.operations.at(-1);
  const intro = found && first && last ? `Found ${found} source ${found === 1 ? "file" : "files"} in ${indexCount} Index ${indexCount === 1 ? "job" : "jobs"}${indexCount === 1 ? ` on ${day(first)}` : ` from ${day(first)} to ${day(last)}`}.` : "No source discovery is recorded.";
  const counts = new Map<string, { count: number; last: LineageOperation }>();
  for (const event of events) {
    for (const op of event.operations) {
      if (event.discoveries.length && ["Pending", "Duplicate"].includes(op.status)) continue;
      const label = `${actionLabel(op)}${op.recovery ? " (recovery)" : ""}`;
      counts.set(label, { count: (counts.get(label)?.count ?? 0) + 1, last: op });
    }
  }
  return `${intro} ${[...counts].map(([label, item]) => `${label}${item.count > 1 ? ` ${item.count} times; last by` : " by"} ${shortJob(item.last)} on ${day(item.last)}.`).join(" ")} Now: ${recordedNow(tree)}`;

}

export interface LaneState { sources: Set<number>; library: boolean; rejects: boolean; everLibrary: boolean }
export interface LaneRow { before: boolean[]; after: boolean[]; dots: number[]; curves: [number, number, boolean][]; ended: number[]; libraryDashed: boolean }
export function laneRows(tree: Lineage, events: TimelineEvent[]): Map<string, LaneRow> {
  const files = new Map(tree.files.map(file => [file.file_id, file]));
  const sources = sourceLanes(tree);
  const state: LaneState = { sources: new Set(), library: false, rejects: false, everLibrary: false };
  const active = () => [0, 1].map(lane => [...state.sources].some(id => sources.get(id) === lane)).concat(state.everLibrary, state.rejects);
  const rows = new Map<string, LaneRow>();
  for (const event of events) {
    const row: LaneRow = { before: active(), after: [], dots: [], curves: [], ended: [], libraryDashed: state.everLibrary && !state.library };
    for (const file of event.discoveries) { state.sources.add(file.file_id); row.dots.push(sources.get(file.file_id) ?? 0); }
    for (const op of event.operations) {
      if (event.discoveries.length) continue;
      const source = op.files.find(link => link.role === "source");
      const file = source && files.get(source.file_id);
      const sourceAt = file ? sources.get(file.file_id) ?? 0 : 0;
      if (op.consolidated_into != null) {
        row.curves.push([2, 2, true]); row.dots.push(2);
      } else if (["Copied", "Copied_Only", "Completed", "Found_At_Destination", "Removed_Duplicate"].includes(op.status) && op.action == null) {
        const retained = op.files.some(link => link.role === "retained_copy");
        const target = state.rejects ? 3 : 2;
        row.curves.push([sourceAt, target, retained]); row.dots.push(target);
        if (target === 2) { state.library = true; state.everLibrary = true; }
        if (["Completed", "Removed_Duplicate"].includes(op.status) && source) state.sources.delete(source.file_id);
      } else if (["Rejected", "Rejected_Copied"].includes(op.status)) {
        row.curves.push([2, 3, false]); row.dots.push(3); state.library = false; state.everLibrary = true; state.rejects = true;
      } else if (op.status === "Returned") {
        row.curves.push([3, 2, false]); row.dots.push(2); state.library = true; state.everLibrary = true; state.rejects = false;
      } else row.dots.push(state.rejects ? 3 : state.library ? 2 : sourceAt);
    }
    row.after = active(); row.ended = [0, 1].filter(lane => row.before[lane] && !row.after[lane]);
    row.dots = [...new Set(row.dots)]; rows.set(event.key, row);
  }
  return rows;
}
