// The webui/ API modules' response shapes and a small fetch wrapper.

export type CatalogState = "missing" | "ok" | "incompatible" | "error";

// What Rejects holds now, and what has been emptied from it so far (webui-spec 7.8).
export interface RejectsSummary {
  photos: number;
  bytes: number;
  oldest_rejected_at: string | null;
  emptied: { photos: number; bytes: number };
}

export interface Status {
  state: CatalogState;
  detail: string | null;
  photos: number;
  indexed: boolean;
  library_photos?: number;
  // What a Copy all and a Move all would take, across the whole catalog.
  eligible: { copy: number; move: number };
  // Unorganized source files held for attention, separate from ready transfers.
  held?: number;
  copied: number;
  // Rejected after a Copy, their source still in place: a Move removes it (engine-spec 9.5).
  rejected_with_source: number;
  // Null when the catalog cannot be read. `reminder`: past a size or age limit (Settings).
  rejects: (RejectsSummary & {
    reminder: { over_size: boolean; over_age: boolean; bytes_limit: number | null; days_limit: number | null };
  }) | null;
  application_data: string;
  catalog_backups: string;
  // Which build is running: the release, and the branch and commit it was built from.
  version?: { release: string | null; branch: string | null; commit: string | null };
  active_job: Run | null;
}

// The navigation sidebar's counts (GET /photos/places): each place whole, and each Look
// into shortcut as Library with only that filter on.
export type PlaceView = "unorganized" | "organized" | "review" | "rejects" | "similar";
export interface Places { places: Record<PlaceView, number>; warnings: { attention: number } }

// "source": every photo whose original is still in the source (Source folders).
export type View = "review" | "all" | "unorganized" | "organized" | "similar" | "suspicious" | "rejects" | "source";
// A job acting on photos; Reject and Return to library need a selection or a folder.
export type ActionMode = "copy" | "move" | "reject" | "return";
// Where a photo is, for selecting: a selection holds library photos or photos in Rejects,
// never both (webui-spec 2), so each action on it has one meaning.
export type Place = "library" | "rejects";
export const placeOf = (status: string): Place =>
  status === "Rejected" || status === "Rejected_Copied" ? "rejects" : "library";
export type Sort = "duplicates" | "newest" | "oldest" | "largest" | "smallest" | "name" | "matches" | "bookmark";

export interface MetadataSourceView {
  id: string; kind: string; label: string; version_id?: number;
  fields: Record<string, unknown>; tags: Record<string, unknown>; available: boolean;
  issues: { code: string; detail?: string }[];
}
export interface MetadataView {
  photo_id: number; capture_id: number | null; primary_id: string | null; sources: MetadataSourceView[];
  issues: { code: string; detail?: string }[]; recorded: boolean; applied: boolean;
  warnings?: { code: string; detail?: string; reason: string }[];
  notice: string | null; field_sources: Record<string, string>;
}

export interface EditDuplicate { photo_id: number; filename: string; path: string }
export interface PhotoNames { photo_id: number; current_path: string; candidates: {name: string; seen_at: string[]}[] }
export interface RenamePreview { photo_id: number; current_path: string; new_path: string; collision: boolean; unchanged: boolean; token: string }
export interface RotationChoice { photo_id: number; turns: number }
export interface RotationPlan { items: { photo_id: number; filename: string; turns: number; error: string | null;
  before?: number; after?: number; duplicate?: EditDuplicate | null; target?: DateEditContext["target"]; no_change?: boolean; edit?: Record<string, unknown> }[] }
export interface DateEditContext {
  capture_id: number; target: { source_id: string; kind: string; create: boolean };
  date: { present: boolean; value: string | null }; current_path: string; can_clear: boolean;
}
export interface DateEditPreview {
  edit: Record<string, unknown>; token: string; target: DateEditContext["target"];
  before: DateEditContext["date"]; after: string; no_change: boolean; duplicate?: EditDuplicate | null;
  filing: { current: string; proposed: string; change: boolean; collision_renamed?: boolean };
}

export interface PrimaryPreview {
  edit: Record<string, unknown>; token: string; source_id: string; label: string; kind: string;
  version_id: number | null; before: Record<string, unknown>; after: Record<string, unknown>;
  differences: string[]; filing: DateEditPreview["filing"];
}

export interface ImportChoice {
  photo_id: number; kind: "association" | "primary";
  selection: {capture_id:number;sidecar?:string;owner_ids?:number[];primary_id?:string};
}
export interface ImportChoiceContext {
  photo_id:number;capture_id:number;filename:string;primary_id:string|null;needs_primary:boolean;
  blockers:{code:string}[];
  sidecars:{path:string;fields:Record<string,unknown>;needs_choice:boolean;saved:boolean;can_choose:boolean;owner_ids:number[];
    candidates:{path:string;file_id:number|null;photo_id:number|null;selectable:boolean}[]}[];
  sources:{id:string;label:string;fields:Record<string,unknown>}[];
}
export interface ImportChoicePreview {
  choice:ImportChoice;token:string;filename:string;owners:string[];primary_id:string|null;
  effective:Record<string,unknown>|null;
  differences:{field:string;before:{present:boolean;value:unknown};after:{present:boolean;value:unknown}}[];
}
export interface MetadataAttention {
  issues: {code: string; reason: string; files: string[]; detail: string | null}[];
  action: string;
}

export interface PhotoItem {
  name_context?: { clashes: boolean; folder: string | null; original_paths: string[]; renamed_on_arrival: boolean };
  thumbnail_revision?: number;
  metadata_attention?: MetadataAttention | null;
  id: number;
  status: string;
  file_size: number | null;
  date_taken: string | null;
  date_source: string | null;
  date_warning: string | null;
  filename: string;
  duplicates: number;
  similar_count?: number | null;
  // A Failed photo's latest failure reason, for its badge's hover.
  failure?: string | null;
  // Why a Move kept this Copied photo's original in the source, when one did.
  kept?: string | null;
  // When a photo in Rejects was rejected.
  rejected_at?: string | null;
  review?: Pick<ReviewDetail, "reasons" | "location">;
}

export interface ReviewDetail {
  reasons: { reason: string; label: string; message: string; bookmark_reason?: string }[];
  history: { id: number; reason: string; action: string; note: string; created_at: string; bookmark_reason?: string }[];
  revision: number; sha1: string | null; location: string;
}
export interface PhotoPage {
  date_min_year: number;
  index_summary?: { discovery: Discovery | null; last_index: { id: number; started_at: string } | null; photos: number; ready: number; unfinished: number; metadata_held?: number; duplicates: number; small: number; minimum: number | null; unknown_dimensions: number; suspicious: number; undated: number; failed: number; similar: null } | null;
  elsewhere?: Record<string, number>;
  chips?: Record<string, number>;
  reasons?: Record<string, number>;
  items: PhotoItem[];
  page: number;
  page_size: number;
  total: number;
  // Unfiltered totals per view (and No usable capture date within the current view).
  counts: Record<View | "undated", number>;
  similarity: { threshold: number; pending: number; unavailable: number } | null;
  // Each view under every filter now on, for the sidebar's places and for suggesting another
  // view; `undated` is No usable capture date within this view under the other filters.
  matches: Record<View | "undated", number>;
  // What Rejects holds now, with the Rejects view.
  rejects?: RejectsSummary | null;
}

export interface PhotoPosition {
  position: number | null;
  page: number | null;
  previous_id: number | null;
  next_id: number | null;
}

// What narrows the gallery: the view, the search, No usable capture date, and the date tree's
// "Show only" years and months ("2023", "2023-06", "none").
export interface BrowseFilters {
  similar?: boolean; suspicious?: boolean; reason?: string; size_below?: number; source_summary?: string; other_names?: boolean;
  set_reference?: number;
  group_sets?: boolean;
  match_min?: number;
  // "job" with `run`: the photos a job recorded, wherever they are now (webui-spec 2).
  view: View | "job";
  run?: number;
  q: string;
  undated: boolean;
  dates?: string[];
  types?: string[];
  folders?: string[];
  // The folder tree only: list every catalogued folder, at 0 where nothing is shown.
  every?: boolean;
}

// A source folder in the Folders tree (GET /photos/folders): its path relative to the
// source, the name shown (a folded chain reads "Camera / Nikon D750"), its photos under
// the filters, and what a Copy or Move of it would take, whatever the filters.
export interface FolderNode {
  path: string;
  name: string;
  photos: number;
  eligible: { copy: number; move: number };
  // End of the latest completed Index that read this whole folder, or null.
  last_indexed: string | null;
  folders: FolderNode[];
}
export interface FolderTree {
  folders: FolderNode[];
  top_files: { photos: number; eligible: { copy: number; move: number }; last_indexed: string | null };
  outside: number;
}

function browseQuery(f: BrowseFilters): URLSearchParams {
  const query = new URLSearchParams({ view: f.view });
  if (f.set_reference != null) query.set("set_reference", String(f.set_reference));
  if (f.group_sets) query.set("group_sets", "true");
  if (f.match_min != null) query.set("match_min", String(f.match_min));
  if (f.run != null) query.set("run", String(f.run));
  if (f.similar) query.set("similar", "true");
  if (f.suspicious) query.set("suspicious", "true");
  if (f.size_below != null) query.set("size_below", String(f.size_below));
  if (f.other_names) query.set("other_names", "1");
  if (f.source_summary) query.set("source_summary", f.source_summary);
  if (f.reason) query.set("reason", f.reason);
  if (f.q) query.set("q", f.q);
  if (f.undated) query.set("undated", "true");
  (f.dates ?? []).forEach((d) => query.append("date", d));
  (f.types ?? []).forEach((t) => query.append("type", t));
  (f.folders ?? []).forEach((d) => query.append("folder", d));
  if (f.every) query.set("every", "true");
  return query;
}

export interface SelectionPage {
  pair_retries?: number;
  items: PhotoItem[];
  page: number;
  page_size: number;
  total: number;
  missing: number[];
  // Those in Rejects: a selection holds one place (Place, below).
  in_rejects?: number[];
  // What each action would take of the selection, for the selection bar.
  actions?: { copy: number; move: number; reject: number; return: number };
  // With `action`: the selected photos that action takes, for its review.
  takes?: number[];
}

export interface Timeline {
  months: { month: string; count: number }[];
  undated: number;
}

export interface Copy {
  id: number;
  status: string;
  source_path: string | null;
  dest_path: string | null;
  file_size: number | null;
}

export interface AccessSettings {
  hosts: string[];
  protected_hosts: string[];
  effective_hosts: string[];
  revision: number;
  current_host: string;
  current_removed?: boolean;
}

export interface PairRetryGroup { mode: "copy" | "move"; file_ids: number[]; token: string }
export interface PairRetryPreview {
  items: { photo_id: number; issue_id: number; operation_id: number; filename: string; mode: "copy" | "move";
    delivery: { photo: "verified" | "incomplete" | "unknown"; xmp: "verified" | "incomplete" | "unknown" };
    failure_context: { stage: string; paths: string[] } | null;
    summary: string; blocked: string | null; source: string; destination: string; sidecar_source: string; sidecar_destination: string }[];
  groups: PairRetryGroup[];
}
export interface FileIssue {
  category?: "unestablished_outcome" | "metadata_pair_incomplete";
  issue_id: number; operation_id: number; summary: string; opened_at: string;
  evidence: {location: string; path: string; kind: string; result: string; observed_at: string; details: string | null}[];
}

export interface PhotoDetail {
  metadata_attention?: MetadataAttention | null;
  issues: FileIssue[];
  failure: string | null;
  visual_issue: string | null;
  id: number;
  status: string;
  filename: string;
  source_path: string | null;
  dest_path: string | null;
  dest_path_is_projection: boolean;
  has_collision_rename: boolean;
  file_size: number | null;
  file_modified: number | null;
  date_taken: string | null;
  date_source: string | null;
  date_warning: string | null;
  date_offset: string | null;
  exif_dates: { field: "taken" | "digitized" | "modified"; value: string; offset: string | null }[];
  camera: string | null;
  iso: number | string | null;
  aperture: number | string | null;
  shutter: number | string | null;
  display_width?: number | null; display_height?: number | null;
  width: number | null;
  height: number | null;
  sha1: string | null;
  phash: string | null;
  duplicates: Copy[];
  // Every tag the Index recorded, [name, value], sorted by name.
  metadata: [string, unknown][];
  thumbnail: { availability: string; failure_category: string | null; failure_detail: string | null };
}

export interface Phase {
  phase: string;
  total: number | null;
  done: number;
  counts: Record<string, number>;
  started_at: string;
  updated_at: string;
}

export type Verdict = "success" | "partial" | "originals_kept" | "none_succeeded" | "stopped" | "no_change" | "cancelled" | "interrupted" | "running";

export interface Outcome {
  verdict: Verdict;
  succeeded: number;
  failed: number;
  skipped: number;
  cancelled: number;
  run_level_issues: number;
  recovered_earlier_work: number;
  skip_reasons: Record<string, number>;
  // Why the requested work failed, by reason (paths removed), for the hover.
  failure_reasons?: Record<string, number>;
  // A Move's photos copied but not moved, because the original could not be deleted.
  copied_only?: number;
  kept_reasons?: Record<string, number>;
  total: number | null;
  counts: Record<string, number>;
}

export interface Discovery {
  files_found: number; eligible: number; photos: Record<string, number>;
  disabled_photos: Record<string, number>; sidecars: number; videos: number; other: number;
  partial: boolean; unreadable: number;
}

export interface Run {
  discovery?: Discovery | null;
  id: number | null;
  mode: string | null;
  status: string;
  started_at?: string;
  ended_at?: string | null;
  targeting?: Record<string, unknown> | null;
  questions?: SafetyQuestion[];
  same_mode_retry?: boolean;
  progress?: Phase[];
  outcome?: Outcome;
  presented_status?: string;
  awaiting_reconciliation?: boolean;
  cancellable?: boolean;
  unrecorded?: boolean;
}

export interface JobState {
  active: Run | null;
  last: Run | null;
}

export type SafetyQuestion = "source_empty" | "network_destination";
export type SafetyAnswer = "confirm_empty" | "retry" | "copy" | "confirm_move";

export interface Setting<T> {
  value: T;
  revision: number;
  default: T;
}

export interface ExtensionSupport {
  extension: string;
  supported: boolean;
  warning: string | null;
}

export type XmpAssociation = "ask" | "raw_only" | "non_raw_only" | "all";
export type MetadataWriteTarget = "xmp" | "embedded";

export interface Settings {
  xmp_association: Setting<XmpAssociation>;
  metadata_write_raw: Setting<MetadataWriteTarget>;
  metadata_write_non_raw: Setting<MetadataWriteTarget>;
  suspicious_min_year: Setting<number>;
  small_image_min: Setting<number | null>;
  workers: Setting<number> & { detected: number; host: number; limited_by: "cpu_quota" | "cpu_set" | null };
  exts: Setting<string[]> & { support: ExtensionSupport[] };
  backup_retention: Setting<number>;
  // Null is off.
  rejects_reminder_bytes: Setting<number | null>;
  rejects_reminder_days: Setting<number | null>;
  job_active: boolean;
}

export interface MetadataChoiceComparison {
  photo_id:number; filename:string; revision:number; saved_at:string;
  owners:string[]; assigned_to_photo:boolean|null;
  historical:{label:string; fields:Record<string,unknown>; available:boolean; sha256:string|null};
  primary:MetadataSourceView|null; notice:string|null; issues:{code:string; detail?:string}[];
}

export interface MetadataHistoryPage {
  items: { id:string; stage:"saved"|"applied"; kind:string; timestamp:string;
    filename:string; photo_id:number|null; run_id:number|null; mode:string|null;
    revision:number|null; applied_choices:number[]; primary:string|null; sidecar:string|null; owners:string[];
    date_taken:string|null }[];
  page:number; page_size:number; total:number;
}

export interface Operation {
  consolidated_into: number | null;
  action: "rotation" | "date" | "metadata_source" | "metadata" | null;
  issues: FileIssue[];
  id: number;
  run_id: number;
  mode: string | null;
  photo_id: number | null;
  timestamp: string;
  source_path: string | null;
  dest_path: string | null;
  status: string;
  error_message: string | null;
  photo_status: string | null;
  recovery: boolean;
  run_level: boolean;
}

export interface OperationPage {
  items: Operation[];
  page: number;
  page_size: number;
  total: number;
  status_counts: Record<string, number>;
  run_counts: Record<string, number>;
}

export interface LogFilters {
  metadata_edits?: boolean;
  run: number[];
  status: string[];
  photo: number | null;
  q: string;
  since: string;
  until: string;
}

export function logQuery(f: LogFilters): URLSearchParams {
  const p = new URLSearchParams();
  f.run.forEach((r) => p.append("run", String(r)));
  f.status.forEach((s) => p.append("status", s));
  if (f.metadata_edits) p.set("metadata_edits", "true");
  if (f.photo != null) p.set("photo", String(f.photo));
  if (f.q) p.set("q", f.q);
  if (f.since) p.set("since", f.since);
  if (f.until) p.set("until", f.until);
  return p;
}

export interface BackupAttempt {
  attempt_id: number;
  trigger_kind: "manual" | "post_job" | "pre_action";
  related_run_id: number | null;
  started_at: string;
  ended_at: string | null;
  outcome: "succeeded" | "failed" | "interrupted" | null;
  error_category: string | null;
  error_detail: string | null;
  relative_filename: string | null;
  size: number | null;
  compression_format: string | null;
  availability: "present" | "missing" | "unknown" | "pruned" | null;
}

// The thumbnail cache by kind (webui-spec 4.2.1), from the sizes the engine records.
export interface ThumbnailCache {
  grid: { photos: number; bytes: number };
  previews: { photos: number; bytes: number };
  job_active: boolean;
}
export interface PreviewsFreed { removed: number; bytes_freed: number; not_removed: number }

export interface Backups {
  items: BackupAttempt[];
  storage: { ok: boolean; error_category: string | null; error_detail: string | null };
  retention: number;
  automatic_retained: number;
  present_count: number;
  present_bytes: number;
  last_success: string | null;
  unbacked: { count: number; since: string | null; runs: number[] };
  job_active: boolean;
}

export interface LineageFile {
  file_id: number;
  origin_file_id: number | null;
  origin_kind: "indexed" | "copy" | "observed_destination" | null;
  path: string | null;
  role: "source" | "destination" | null;
  presence: "present" | "removed" | "missing" | null;
  sha1_hash: string | null;
  matches: boolean;
  file_size: number | null;
  indexed_path: string | null;
  created_at: string | null;
  photo_id: number | null;
  photo_status: string | null;
}

export interface LineageOperation {
  consolidated_into: number | null;
  action: "rotation" | "date" | "metadata_source" | "metadata" | null;
  id: number;
  run_id: number;
  mode: string | null;
  status: string;
  timestamp: string;
  error_message: string | null;
  photo_id: number | null;
  source_path: string | null;
  dest_path: string | null;
  recovery: boolean;
  files: { file_id: number; role: "source" | "destination" | "retained_copy" }[];
}

export interface Lineage {
  photo_id: number;
  sha1: string | null;
  photos: number[];
  files: LineageFile[];
  operations: LineageOperation[];
  // The jobs this photo was chosen for by hand (a selection), whatever each did with it.
  selected_by: { run_id: number; mode: string; status: string; started_at: string }[];
}

export interface Stats {
  library: { failed_source: number;
    photos: number; bytes: number; organized: number; organized_bytes: number; not_organized: number;
    formats: { format: string; photos: number; bytes: number }[];
    cameras: { name: string; photos: number }[];
    lenses: { name: string; photos: number }[];
    megapixels: { band: string; photos: number }[];
    under_1mp: number;
    orientation: { landscape: number; portrait: number; square: number };
    with_location: number;
  };
  dates: {
    per_year: { year: string; photos: number }[];
    min_year: number; max_year: number;
    oldest: string | null; newest: string | null;
    busiest_day: { day: string; photos: number } | null;
    undated: number; undated_no_date: number; undated_unusable: number; with_time_zone: number;
  };
  duplicates: {
    groups: number; extra_copies: number; bytes: number; saved_at_destination: number;
    move_would_free: number; freed_by_moves: number; copies_not_written: number;
    coverage: { last_complete_scan: string | null; established_by_run: number | null;
                scans_with_issues_since: number; run_ids_since: number[] };
    by_folder: { folder: string; files: number; duplicates: number; duplicate_bytes: number }[];
  };
  activity: {
    jobs: Record<string, number>; last_index: string | null; copied: number; moved: number;
    bytes_transferred: number; bytes_per_second: number | null; failures: Record<string, number>;
    renames: number; metadata_edits: { photos: number; dates: number; rotations: number; primary_source: number; other: number };
  };
  health: {
    low_detail_photos: number;
    last_backup: string | null; backup_bytes: number; backups: number; unbacked_changes: number;
    catalog_bytes: number; thumbnail_cache: { size: number; photos: number; bytes: number }[];
    destination_check: { at: string; findings: Record<string, number> } | null;
  };
  rejects: RejectsSummary;
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public body: Record<string, unknown>) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    method,
    signal,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const code = (data && (data.error as string)) || `http_${response.status}`;
    const message = (data && (data.message as string)) || `The server answered ${response.status}.`;
    throw new ApiError(response.status, code, message, data ?? {});
  }
  return data as T;
}

type Submission = { id: string; path: string; body: Record<string, unknown> };
const SUBMISSION_KEY = "ns.pendingSubmission";
let savedSubmission: Submission | null = null;
try {
  const saved = JSON.parse(sessionStorage.getItem(SUBMISSION_KEY) || "null");
  if (saved && /^[a-f0-9]{32}$/.test(saved.id) &&
      (saved.path === "/api/v1/jobs/start" || /^\/api\/v1\/runs\/\d+\/answer$/.test(saved.path)) &&
      saved.body && typeof saved.body === "object" && !Array.isArray(saved.body)) savedSubmission = saved;
} catch { /* No valid saved submission. New submissions still require persistence. */ }
let submissionState = { pending: savedSubmission, checking: !!savedSubmission, resolved: null as Run | null, error: null as string | null };
const submissionListeners = new Set<() => void>();
const acceptedJobListeners = new Set<(run: Run) => void>();
export const subscribeJobAccepted = (listener: (run: Run) => void) => {
  acceptedJobListeners.add(listener);
  return () => { acceptedJobListeners.delete(listener); };
};
let submissionPromise: Promise<Run> | null = null;
let resolveSubmission: ((run: Run) => void) | null = null;
let rejectSubmission: ((error: ApiError) => void) | null = null;
let checkingRequest: string | null = null;
let sendingRequest: string | null = null;
let lookupTimer: ReturnType<typeof setTimeout> | null = null;
function notifySubmission() {
  submissionState = { ...submissionState };
  submissionListeners.forEach((listener) => listener());
}
export const submissionSnapshot = () => submissionState;
export const subscribeSubmission = (listener: () => void) => {
  submissionListeners.add(listener);
  return () => { submissionListeners.delete(listener); };
};
function settleSubmission(run: Run | null, error?: ApiError) {
  const wasUncertain = submissionState.checking;
  if (lookupTimer) clearTimeout(lookupTimer);
  lookupTimer = null;
  try { sessionStorage.removeItem(SUBMISSION_KEY); } catch { /* already settled in memory */ }
  const resolve = resolveSubmission, reject = rejectSubmission;
  resolveSubmission = null; rejectSubmission = null; submissionPromise = null;
  submissionState = { pending: null, checking: false, resolved: wasUncertain ? run : null, error: error?.message ?? null };
  notifySubmission();
  if (run) {
    acceptedJobListeners.forEach((listener) => listener(run));
    resolve?.(run);
  } else if (error) reject?.(error);
}
export async function checkSubmission() {
  const pending = submissionState.pending;
  if (!pending || checkingRequest === pending.id) return;
  checkingRequest = pending.id;
  try {
    const result = await request<{ state: string; run: Run | null }>("GET", `/api/v1/job-requests/${pending.id}`,
      undefined, AbortSignal.timeout(5000));
    if (submissionState.pending?.id === pending.id && result.state === "accepted" && result.run?.id != null) {
      settleSubmission(result.run);
    }
  } catch { /* An unavailable lookup leaves acceptance unknown. */ }
  finally {
    if (checkingRequest === pending.id) checkingRequest = null;
    if (submissionState.pending?.id === pending.id) {
      submissionState.checking = true;
      notifySubmission();
      if (lookupTimer) clearTimeout(lookupTimer);
      lookupTimer = setTimeout(() => void checkSubmission(), 2000);
    }
  }
}
export async function retrySubmission() {
  const pending = submissionState.pending;
  if (!pending || sendingRequest === pending.id) return;
  sendingRequest = pending.id;
  try {
    const run = await request<Run>("POST", pending.path, { ...pending.body, request_id: pending.id }, AbortSignal.timeout(10000));
    if (run?.id == null) throw new Error("Unrecognized acceptance response");
    if (submissionState.pending?.id === pending.id) settleSubmission(run);
  } catch (error) {
    if (submissionState.pending?.id !== pending.id) return;
    if (error instanceof ApiError && error.status >= 400 && error.status < 500 &&
        !(submissionState.checking && error.code === "job_already_running")) {
      settleSubmission(null, error);
    } else {
      submissionState.checking = true;
      notifySubmission();
      void checkSubmission();
    }
  } finally { if (sendingRequest === pending.id) sendingRequest = null; }
}
function submitJob(path: string, body: Record<string, unknown>): Promise<Run> {
  if (submissionState.pending) {
    if (submissionPromise && submissionState.pending.path === path && JSON.stringify(submissionState.pending.body) === JSON.stringify(body))
      return submissionPromise;
    return Promise.reject(new ApiError(409, "submission_pending", "A previous submission is still being checked. Resolve it before starting another job.", {}));
  }
  const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
  const pending = { id, path, body };
  try { sessionStorage.setItem(SUBMISSION_KEY, JSON.stringify(pending)); }
  catch { return Promise.reject(new ApiError(409, "submission_storage", "Allow browser session storage so this job can be tracked before starting it.", {})); }
  submissionState = { pending, checking: false, resolved: null, error: null };
  const promise = new Promise<Run>((resolve, reject) => { resolveSubmission = resolve; rejectSubmission = reject; });
  submissionPromise = promise;
  notifySubmission();
  void retrySubmission();
  return promise;
}

export type MatchScope = "library" | "rejects";

export const LOW_DETAIL_NOTE = "Mostly dark or plain: matches like this are often unrelated photos.";

export interface MatchPhoto {
  low_detail?: boolean; low_detail_match?: boolean;
  id: number; filename: string; file_size: number | null; date_taken: string | null;
  display_width?: number | null; display_height?: number | null;
  status: string; width: number | null; height: number | null; matches?: number; score?: number;
}
export interface MatchPage {
  items: MatchPhoto[]; total: number; page: number; page_size: number;
  state: { photos: number; unavailable: number; pending: number };
  reference?: MatchPhoto | null;
  availability?: "available" | "not_available" | "hash_unavailable";
  largest_pixels?: number | null;
  largest_match?: MatchPhoto | null;
  query_ms?: number;
}

export const MATCH_THRESHOLDS = [75, 80, 85, 90, 95, 100];
// The gallery percentage this browser last chose (ns.matchMin), 90 until one is chosen.
export function savedMatchMinimum(): number {
  try {
    const value = Number(localStorage.getItem("ns.matchMin"));
    if (MATCH_THRESHOLDS.includes(value)) return value;
  } catch { /* Storage is optional. */ }
  return 90;
}

export interface MatchCounts {
  availability: "available" | "not_available" | "hash_unavailable";
  counts: { threshold: number; count: number }[];
  pending: number;
}

// Two photos for side by side.
export interface MatchPair {
  reference: MatchPhoto & { sha1: string }; candidate: MatchPhoto & { sha1: string };
  exact: boolean; distance: number | null; score: number | null; low_detail_match?: boolean;
}
export interface MatchDiagnostics {
  state: MatchPage["state"]; distinct_hashes: number; stored_pairs: number; query_ms: number;
  last_comparison: { run_id: number; started_at: string; updated_at: string; elapsed_seconds: number } | null;
}

export type SimilarityRecoveryPage = {
  items: { id: number; filename: string; kind: string; reason: string; message: string; retryable: boolean; action: "generate" | "recheck" | null }[];
  total: number; retryable: number; generatable: number; state: { unavailable: number; pending: number }; page: number; page_size: number;
};

export interface NotificationPage { items: { run: Run; read: boolean }[]; next_before: number | null }

export const api = {
  unreadNotifications: () => request<{ unread: number }>("GET", "/api/v1/notifications/unread"),
  notifications: (before?: number) => request<NotificationPage>("GET", `/api/v1/notifications${before ? `?before=${before}` : ""}`),
  readNotifications: (run_ids: number[]) => request<{ read_ids: number[] }>("PUT", "/api/v1/notifications/read", { run_ids }),
  access: () => request<AccessSettings>("GET", "/api/v1/access"),
  saveAccess: (hosts: string[], revision: number, confirm_current_host = false) =>
    request<AccessSettings>("PUT", "/api/v1/access", { hosts, revision, confirm_current_host }),
  review: (id: number) => request<ReviewDetail>("GET", `/api/v1/photos/${id}/review`),
  reviewDecision: (id: number, detail: ReviewDetail, reason: string, action: string, note: string, request_id: string, bookmark_reason?: string) =>
    request<ReviewDetail>("POST", `/api/v1/photos/${id}/review`, {
      photo_id: id, sha1: detail.sha1, revision: detail.revision, reason, action, note, request_id, ...(bookmark_reason ? { bookmark_reason } : {}),
    }),
  similarityRecovery: (page = 1, photoId?: number) => request<SimilarityRecoveryPage>("GET", `/api/v1/similar/recovery?page=${page}${photoId == null ? "" : `&photo_id=${photoId}`}`),
  repairSimilarity: (scope: "missing" | "comparisons", photo_id?: number) => submitJob("/api/v1/similar/recovery", { scope, ...(photo_id == null ? {} : { photo_id }) }),
  run: (id: number) => request<Run>("GET", `/api/v1/runs/${id}`),
  matchCounts: (photo: number, scope: MatchScope = "library") => request<MatchCounts>("GET", `/api/v1/similar/${photo}/counts?scope=${scope}`),
  matchDiagnostics: () => request<MatchDiagnostics>("GET", "/api/v1/similar/diagnostics"),
  matchPair: (reference: number, candidate: number) =>
    request<MatchPair>("GET", `/api/v1/similar/${reference}/pair/${candidate}`),
  matches: (query: URLSearchParams, photo: number | null = null) =>
    request<MatchPage>("GET", `/api/v1/similar${photo == null ? "" : `/${photo}`}?${query}`),
  jobState: (signal?: AbortSignal) => request<JobState>("GET", "/api/v1/jobs/active", undefined, signal),
  status: () => request<Status>("GET", "/api/v1/status"),
  createCatalog: () => request<Status>("POST", "/api/v1/catalog"),
  settings: () => request<Settings>("GET", "/api/v1/settings"),
  saveSettings: (values: Record<string, unknown>, revisions: Record<string, number>) =>
    request<Settings>("PUT", "/api/v1/settings", { values, revisions }),
  validateExtension: (extension: string) =>
    request<ExtensionSupport>("POST", "/api/v1/settings/validate-extension", { extension }),
  photos: (params: BrowseFilters & { sort: Sort; page: number; page_size: number }) => {
    const query = browseQuery(params);
    query.set("sort", params.sort);
    query.set("page", String(params.page));
    query.set("page_size", String(params.page_size));
    return request<PhotoPage>("GET", `/api/v1/photos?${query}`);
  },
  photoPosition: (params: BrowseFilters & { photo_id: number; sort: Sort; page_size: number; ids?: number[] }) =>
    request<PhotoPosition>("POST", "/api/v1/photos/position", params),
  // Without `dates` for the date tree's counts; with them for the page a jump lands on.
  places: (matchMin: number) => request<Places>("GET", `/api/v1/photos/places?match_min=${matchMin}`),
  timeline: (params: BrowseFilters) => request<Timeline>("GET", `/api/v1/photos/timeline?${browseQuery(params)}`),
  types: (params: BrowseFilters) =>
    request<{ types: { type: string; photos: number }[] }>("GET", `/api/v1/photos/types?${browseQuery(params)}`),
  // `folders` here keeps ticked folders listed; the tree's counts ignore its own filter.
  folders: (params: BrowseFilters) => request<FolderTree>("GET", `/api/v1/photos/folders?${browseQuery(params)}`),
  photoIds: (params: BrowseFilters) =>
    request<{ ids: number[]; total: number; in_rejects: number[] }>("GET", `/api/v1/photos/ids?${browseQuery(params)}`),
  selection: (ids: number[], sort: Sort, page: number, page_size: number, match_min = 75, action?: ActionMode) =>
    request<SelectionPage>("POST", "/api/v1/photos/selection", { ids, sort, page, page_size, match_min, ...(action ? { action } : {}) }),
  metadataChoiceComparison: (photo:number, revision:number) =>
    request<MetadataChoiceComparison>("GET", `/api/v1/photos/${photo}/metadata-choices/${revision}/comparison`),
  metadataHistory: (f: LogFilters, page: number, pageSize: number) => {
    const p=logQuery(f);p.set("page",String(page));p.set("page_size",String(pageSize));
    return request<MetadataHistoryPage>("GET",`/api/v1/metadata-history?${p}`);
  },
  operations: (f: LogFilters, page: number, pageSize: number) => {
    const p = logQuery(f);
    p.set("page", String(page));
    p.set("page_size", String(pageSize));
    return request<OperationPage>("GET", `/api/v1/operations?${p}`);
  },
  exportUrl: (f: LogFilters, format: "csv" | "json") => {
    const p = logQuery(f);
    p.set("format", format);
    return `/api/v1/operations/export?${p}`;
  },
  retryIds: (f: LogFilters, requestedOnly = false) =>
    request<{ photo_ids: number[] }>(
      "GET", `/api/v1/operations/photo-ids?${logQuery(f)}${requestedOnly ? "&requested_only=true" : ""}`),
  backups: () => request<Backups>("GET", "/api/v1/backups"),
  backupNow: () => request<BackupAttempt>("POST", "/api/v1/backups"),
  backupDownloadUrl: (id: number) => `/api/v1/backups/${id}/download`,
  thumbnails: () => request<ThumbnailCache>("GET", "/api/v1/thumbnails"),
  rebuildThumbnails: (scope: "missing" | "all") => submitJob("/api/v1/thumbnails/rebuild", { scope }),
  clearPreviews: () => request<PreviewsFreed>("POST", "/api/v1/thumbnails/clear-previews"),
  stats: () => request<Stats>("GET", "/api/v1/stats"),
  uiState: () => request<{ dismissed_run: number | null }>("GET", "/api/v1/ui-state"),
  saveUiState: (values: { dismissed_run: number }) => request<{ dismissed_run: number | null }>("PUT", "/api/v1/ui-state", values),
  runs: (limit = 100) => request<{ runs: Run[] }>("GET", `/api/v1/runs?limit=${limit}`),
  lineage: (id: number) => request<Lineage>("GET", `/api/v1/photos/${id}/lineage`),
  fileIssues: (id: number) => request<{items: FileIssue[]}>("GET", `/api/v1/photos/${id}/issues`),
  pairRetryPreview: (file_ids: number[]) => request<PairRetryPreview>("POST", "/api/v1/pair-retries/preview", {file_ids}),
  retryPairs: (group: PairRetryGroup, request_id: string) => request<Run>("POST", "/api/v1/pair-retries/start", {...group,request_id}),
  checkIssue: (issue_id: number, request_id: string) => request<Run>("POST", "/api/v1/issues/check", {issue_id,request_id}),
  importChoices: (id:number) => request<ImportChoiceContext>("GET", `/api/v1/photos/${id}/import-choices`),
  previewImportChoice: (id:number, choice:ImportChoice) => request<ImportChoicePreview>("POST", `/api/v1/photos/${id}/import-choices/preview`, choice),
  confirmImportChoice: (id:number, preview:ImportChoicePreview, request_id:string) => request<{revision:number;message:string}>("POST", `/api/v1/photos/${id}/import-choices/confirm`, {choice:preview.choice,token:preview.token,request_id}),
  photoNames: (id: number) => request<PhotoNames>("GET", `/api/v1/photos/${id}/names`),
  renamePreview: (id: number, name: string) => request<RenamePreview>("POST", `/api/v1/photos/${id}/rename-preview`, { name }),
  renamePhoto: (id: number, name: string, token: string) => submitJob(`/api/v1/photos/${id}/rename`, { name, token }),
  rotationPreview: (rotations: RotationChoice[]) => request<RotationPlan>("POST", "/api/v1/rotations/preview", { rotations }),
  saveRotations: (edits: Record<string, unknown>[]) => submitJob("/api/v1/rotations/save", { edits }),
  dateContext: (id: number) => request<DateEditContext>("GET", `/api/v1/photos/${id}/date-edit`),
  datePreview: (id: number, body: { capture_id: number; value?: string; donor_id?: string }) => request<DateEditPreview>("POST", `/api/v1/photos/${id}/date-preview`, body),
  saveDate: (id: number, preview: DateEditPreview) => submitJob(`/api/v1/photos/${id}/date-save`, { edit: preview.edit, token: preview.token }),
  primaryPreview: (id: number, sourceId: string, captureId: number) => request<PrimaryPreview>("POST", `/api/v1/photos/${id}/primary-preview`, {source_id:sourceId,capture_id:captureId}),
  savePrimary: (id: number, preview: PrimaryPreview) => submitJob(`/api/v1/photos/${id}/primary-save`, {edit:preview.edit,token:preview.token}),
  metadata: (id: number) => request<MetadataView>("GET", `/api/v1/photos/${id}/metadata`),
  inspect: (id: number) => request<PhotoDetail>("GET", `/api/v1/photos/${id}/inspect`),
  answerQuestion: (id: number, question: SafetyQuestion, answer: SafetyAnswer) =>
    submitJob(`/api/v1/runs/${id}/answer`, { question, answer }),
  previewMove: (body: MoveScope) => request<MovePreview>("POST", "/api/v1/jobs/move-preview", body),
  startJob: (body: { mode: "index" | ActionMode; file_ids?: number[]; source_subdir?: string; confirm_edited_sources?: boolean; move_preview_token?: string }) =>
    submitJob("/api/v1/jobs/start", body),
  cancelJob: (id: number) => request<{ id: number }>("POST", `/api/v1/jobs/${id}/cancel`),
  thumbnailUrl: (id: number, size: "grid" | "preview" = "grid", revision?: number) =>
    `/api/v1/photos/${id}/thumbnail?size=${size}${revision == null ? "" : `&revision=${revision}`}`,
  // Why a thumbnail is missing: the 404 body carries the recorded reason.
  thumbnailReason: async (id: number, size: "grid" | "preview" = "grid") => {
    const response = await fetch(api.thumbnailUrl(id, size));
    if (response.ok) return null;
    try {
      return (await response.json()) as { availability: string; failure_category: string | null; failure_detail: string | null };
    } catch {
      return { availability: "unavailable", failure_category: null, failure_detail: null };
    }
  },
};

export type MoveScope = { file_ids?: number[]; source_subdir?: string };
export type MovePreview = { file_ids: number[]; token: string; rejected_originals: number;
  edited_originals: { photo_id: number; source: string; filename: string; in_rejects: boolean }[] };
export type MoveSubmission = { mode: "move"; file_ids: number[]; move_preview_token: string; confirm_edited_sources: boolean };
