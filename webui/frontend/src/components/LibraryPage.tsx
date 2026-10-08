import { StableContent } from "./ui/StableContent";
import { PageNavigation } from "./PageNavigation";
import { ReviewWorkspace } from "./ReviewWorkspace";
// The Library: the gallery with its views, filters and selection, the Inspector, and
// the jobs started from it (webui-spec 2 and 4).
import { ReferenceSets } from "./ReferenceSets";
import { readComparison, type ComparisonState } from "../comparisonState";
import { SimilarityRecovery } from "./SimilarityRecovery";
import { PageBoundary } from "./ui/PageBoundary";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type PointerEvent as ReactPointerEvent } from "react";
import { Logo } from "./Logo";
import { PageTools } from "./PageTools";
import { api, ApiError, submissionSnapshot, subscribeSubmission, MATCH_THRESHOLDS, type ActionMode, type Place, placeOf, type PhotoItem, type PhotoPage, type FolderTree, type SelectionPage, type Run, type Sort, type Status, type Timeline, type View } from "../api";
import { count, plural } from "../format";
import { jobLabel, summary, useDismissedRun, useJobFeed } from "../jobs";
import { Gallery } from "./Gallery";
import { Inspector } from "./Inspector";
import { FinishedBanner, JobDrawer } from "./JobDrawer";
import { PAGE_SIZES, Pager } from "./Pager";
import { DatesPanel, dateLabel, datePage } from "./DatesPanel";
import { TypesPanel, typeLabel } from "./TypesPanel";
import { BrowseBySwitch, FoldersPanel, folderLabel, initialBrowseBy, shownFolder, type BrowseBy } from "./FoldersPanel";
import { SelectMenu } from "./SelectMenu";
import { usePaged } from "../paged";
import { ConfirmDialog, transferConfirm, type Confirm } from "./Confirm";
import { Tip } from "./Tip";
import { JobsMenu } from "./JobsMenu";
import { SelectionBar, type SelectionCounts } from "./SelectionBar";
import { RejectsLine, RejectsReminder } from "./RejectsLine";
import { SearchField } from "./ui/SearchField";
import type { MatchView } from "./PhotoMatches";
import { follow, navigate, rememberLibraryQuery, useHeaderHeight, useNavigation } from "../nav";


// Reserve the gallery separately from the filters and the resize handles.
const MIN_SIDE = 320;
const MIN_GALLERY = 420;
// The left panel's width limits when dragged.
const SIDE_MIN = 180;
const SIDE_MAX = 560;
const VIEW_LABEL: Record<View, string> = { all: "Search results", unorganized: "Not organized", organized: "Library", similar: "Has similar photos", suspicious: "Suspicious dates", rejects: "Rejects", review: "Needs review" };
const PLACE_VIEWS: View[] = ["unorganized", "organized", "review", "rejects"];
// The review bar's words for each job a selection can be reviewed for.
// Why a review left selected photos out: what each action takes (catalog.ACTION_STATUSES).
const TAKES: Record<ActionMode, string> = {
  copy: "Copy takes only photos not yet copied",
  move: "Move takes only photos not yet moved",
  reject: "Reject takes only photos already organized",
  return: "Return to library takes only photos in Rejects",
};

const REVIEW_WORDS: Record<ActionMode, { doing: string; done: string; button: string }> = {
  copy: { doing: "copying", done: "copied", button: "Copy these" },
  move: { doing: "moving", done: "moved", button: "Move these" },
  reject: { doing: "rejecting", done: "moved to Rejects", button: "Reject these" },
  return: { doing: "returning to the library", done: "returned to the library", button: "Return these" },
};

function savedSort(view: View): Sort {
  try {
    const value = localStorage.getItem(`ns.sort.${view}`) as Sort;
    if (["newest", "oldest", "largest", "smallest", "name", ...(view === "similar" ? ["matches"] : [])].includes(value)) return value;
  } catch { /* Storage is optional. */ }
  return view === "similar" ? "matches" : "newest";
}
function savedGrouping(): boolean {
  try { return localStorage.getItem("ns.groupSets") !== "false"; } catch { return true; }
}
function savedMatchMinimum(): number {
  try {
    const value = Number(localStorage.getItem("ns.matchMin"));
    if (MATCH_THRESHOLDS.includes(value)) return value;
  } catch { /* Storage is optional. */ }
  return 90;
}
function savePreference(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* Storage is optional. */ }
}

function savedPlace(hasLibrary: boolean): View {
  // A new, empty catalog always starts with its first step, even in a used browser.
  if (!hasLibrary) return "unorganized";
  try { const value = localStorage.getItem("ns.place") as View; if (PLACE_VIEWS.includes(value)) return value; } catch { /* Storage is optional. */ }
  return "organized";
}

// Browsing state lives in the URL, so a refresh or a shared link keeps the place.
function readUrl(hasLibrary = true) {
  const p = new URLSearchParams(window.location.search);
  const legacy = p.get("view") as View;
  const view = legacy === "similar" ? "organized" : legacy === "suspicious" ? "organized" : legacy || savedPlace(hasLibrary);
  const matchPage = Number(p.get("match_page"));
  const similar = (view === "organized" || view === "review" || view === "all") && (legacy === "similar" || p.get("similar") === "1");
  return {
    view: (["all", "unorganized", "organized", "similar", "suspicious", "rejects", "review"] as View[]).includes(view) ? view : "all",
    similar,
    groupSets: p.has("group_sets") ? p.get("group_sets") !== "0" : savedGrouping(),
    suspicious: legacy === "suspicious" || p.get("suspicious") === "1",
    reason: ["small", "later"].includes(p.get("reason") || "") ? p.get("reason")! : "all",
    reviewPhoto: Number(p.get("review_photo")) || null,
    sort: p.get("sort") === "matches" && !similar ? "newest" as Sort : (p.get("sort") as Sort) || savedSort(similar ? "similar" : view),
    matchMin: MATCH_THRESHOLDS.includes(Number(p.get("match_min"))) ? Number(p.get("match_min")) : savedMatchMinimum(),
    q: p.get("q") || "",
    page: Math.max(1, Number(p.get("page")) || 1),
    size: PAGE_SIZES.includes(Number(p.get("size"))) ? Number(p.get("size")) : PAGE_SIZES[0],
    undated: p.get("undated") === "1",
    dates: p.getAll("date"),
    types: p.getAll("type"),
    folders: p.getAll("folder"),
    run: Number.isSafeInteger(Number(p.get("run"))) && Number(p.get("run")) > 0 ? Number(p.get("run")) : null,
    photo: p.get("photo") ? Number(p.get("photo")) : null,
    comparison: readComparison(p),
    inspectorTab: (p.get("tab") === "similar" || (!p.has("tab") && p.has("match"))) ? "similar" as const : "information" as const,
    match: MATCH_THRESHOLDS.includes(Number(p.get("match"))) ? { threshold: Number(p.get("match")),
      page: Number.isSafeInteger(matchPage) && matchPage > 0 ? matchPage : 1 } : null,
  };
}


// Showing only a set of photos, whatever the view, search and dates would hide: the
// selection (Show only selected) or the photos under review. `ids` is fixed
// on entry, so unticking a photo there leaves it on screen, unticked.
// "review" is the selection before a Copy or Move of it: shown in full, with the action
// in a bar above it, so every photo can be looked at and unticked before committing.
type Focus = { kind: "selection" | "review" | "photo" | "set"; ids: number[]; reference?: number; threshold?: number; mode?: ActionMode;
  // Keep this one, reject the rest: the photo kept, shown first and never ticked.
  keep?: number; keepName?: string;
  // A review: selected photos its action does not take, left out of it and counted.
  leftOut?: number };

const NO_ACTIONS: SelectionCounts = { copy: 0, move: 0, reject: 0, return: 0 };

export function LibraryPage({ status, refreshStatus, onOpenSettings }: {
  status: Status;
  refreshStatus: () => void;
  onOpenSettings: () => void;
}) {
  const initial = useRef(readUrl((status.library_photos ?? 0) > 0)).current;
  const [view, setView] = useState<View>(initial.view);
  const [reviewReturn, setReviewReturn] = useState<{ url: string; anchor: number; offset: number; opener: number } | null>(null);
  const restoringReview = useRef<typeof reviewReturn>(null);
  useEffect(() => { if (PLACE_VIEWS.includes(view)) savePreference("ns.place", view); }, [view]);
  const [similar, setSimilar] = useState(initial.similar);
  const [suspicious, setSuspicious] = useState(initial.suspicious);
  const [reason, setReason] = useState(initial.reason);
  const [reviewPhoto, setReviewPhoto] = useState<number | null>(initial.reviewPhoto);
  const reviewFilter = reason;
  const [sort, setSort] = useState<Sort>(initial.sort);
  const [matchMin, setMatchMin] = useState(initial.matchMin);
  const galleryMinimum = matchMin;
  const [q, setQ] = useState(initial.q);
  const [search, setSearch] = useState(initial.q);
  // `jump` is where loading starts (the pager, a date, a filter change); `page` is the
  // page at the top of the screen, which scrolling moves and the address records.
  const [jump, setJump] = useState({ page: initial.page, n: 0 });
  const [page, setVisiblePage] = useState(initial.page);
  const setPage = (p: number) => { setJump((j) => ({ page: p, n: j.n + 1 })); setVisiblePage(p); };
  const [pageSize, setPageSize] = useState(initial.size);
  const [undated, setUndated] = useState(initial.undated);
  const [dates, setDates] = useState<string[]>(initial.dates);
  const [types, setTypes] = useState<string[]>(initial.types);
  const [folders, setFolders] = useState<string[]>(initial.folders);
  // A job's photos (webui-spec 2, after a job): a scope over the gallery, opened from the
  // finished banner; every filter narrows it, and a view button or Back to results leaves it.
  const [jobRun, setJobRun] = useState<number | null>(initial.run);
  // A job started from a job's photos, which the view moves to when it ends, so the line
  // above them and the finished banner describe the same job.
  const [followJob, setFollowJob] = useState<number | null>(null);
  const browseView: View | "job" = jobRun != null ? "job" : view;
  const [folderTree, setFolderTree] = useState<FolderTree | null>(null);
  const [browseBy, setBrowseBy] = useState<BrowseBy>(() => initialBrowseBy(initial.folders, initial.dates));
  const [typeCounts, setTypeCounts] = useState<{ type: string; photos: number }[] | null>(null);
  const [openId, setOpenId] = useState<number | null>(initial.photo);
  const [matchState, setMatchState] = useState<{ photo: number | null; view: MatchView }>({ photo: initial.photo, view: initial.match });
  const [inspectorTab, setInspectorTab] = useState(initial.inspectorTab);
  const [comparison, setComparison] = useState<ComparisonState | null>(initial.comparison);
  const [groupSets, setGroupSets] = useState(initial.groupSets);
  const [exploreReference, setExploreReference] = useState<number | null>(null);
  const reviewSet = (reference: number, candidate: number | null) => {
    setOpenId(reference); setLocate(null); setRevealId(null); setInspectorTab("similar");
    setMatchState({ photo: reference, view: { threshold: matchMin, page: 1 } });
    setComparison({ origin: reference, reference, candidate, threshold: matchMin, page: 1,
      views: {}, linked: false, share: 72 });
  };
  const [comparisonNavigation, setComparisonNavigation] = useState(0);
  useEffect(() => { if (comparison && comparison.origin !== openId) setComparison(null); }, [openId, comparison]);
  const matchView = useMemo(() => matchState.view && ({ ...matchState.view,
    page: matchState.photo === openId ? matchState.view.page : 1 }), [matchState, openId]);
  useEffect(() => {
    setMatchState((current) => current.photo === openId ? current : { photo: openId,
      view: current.view && { ...current.view, page: 1 } });
  }, [openId]);
  const [locate, setLocate] = useState<{ id: number; delta: number } | null>(
    initial.photo == null ? null : { id: initial.photo, delta: 0 });
  const [revealId, setRevealId] = useState<number | null>(null);
  const openFromGallery = (id: number) => {
    setLocate(null); setRevealId(null); setOpenId(id);
    if (similar && jobRun == null) {
      setInspectorTab("similar");
      setMatchState({ photo: id, view: { threshold: focus?.kind === "set" ? focus.threshold! : matchMin, page: 1 } });
    }
  };
  const openAndLocate = (id: number) => { setOpenId(id); setLocate({ id, delta: 0 }); setRevealId(null); };
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [jumpTimeline, setJumpTimeline] = useState<Timeline | null>(null);
  const [focus, setFocus] = useState<Focus | null>(null);
  const similarityPlace = view === "organized" || view === "review";
  const hasAdditionalFilters = suspicious || undated || reason !== "all" || !!q || dates.length > 0 || types.length > 0 || folders.length > 0;
  const groupingUnavailable = hasAdditionalFilters ? "Clear the other filters to group similar photos. Filtered results show every matching photo."
    : focus || jobRun != null ? "Grouping is available in the regular Similar photos results." : null;
  const grouped = similar && similarityPlace && groupSets && !groupingUnavailable;
  // Most matches first is the similar view's; a job's photos fall back to newest.
  const browseSort: Sort = jobRun != null && sort === "matches" ? "newest" : sort;
  useEffect(() => { if (!grouped) setExploreReference(null); }, [grouped]);
  const [focusJump, setFocusJump] = useState({ page: 1, n: 0 });
  const [focusPage, setFocusVisible] = useState(1);
  const setFocusPage = (p: number) => { setFocusJump((j) => ({ page: p, n: j.n + 1 })); setFocusVisible(p); };
  // A notice names its fixes as buttons that apply them, not as instructions.
  const [notice, setNoticeState] = useState<{ text: string; actions: { label: string; run: () => void }[] } | null>(null);
  const setNotice = (text: string | null, actions: { label: string; run: () => void }[] = [], photo?: number) => {
    noticePhoto.current = text == null ? null : photo ?? null;
    setNoticeState(text == null ? null : { text, actions });
  };
  // A notice about one rejected photo lasts only while it is in Rejects: returning it,
  // from the notice or anywhere else, clears it once the job that did so has ended.
  const noticePhoto = useRef<number | null>(null);
  // A date to go to once the date filter that hid it has changed.
  const [pendingJump, setPendingJump] = useState<string | null>(null);
  // Every photo on screen, as the last scroll found them.
  const [onScreen, setOnScreen] = useState<number[]>([]);
  const [datesOpen, setDatesOpen] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  // Library photos or photos in Rejects, never both (webui-spec 2): set by the first photo
  // ticked, cleared with the selection.
  const [place, setPlace] = useState<Place | null>(null);
  useEffect(() => { if (selected.size === 0) setPlace(null); }, [selected]);
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  useNavigation(() => {
    if (window.location.pathname !== "/") return;
    const next = readUrl((status.library_photos ?? 0) > 0);
    setSimilar(next.similar); setGroupSets(next.groupSets); setSuspicious(next.suspicious); setReason(next.reason); setReviewPhoto(next.reviewPhoto);
    setView(next.view); setSort(next.sort); setMatchMin(next.matchMin);
    setQ(next.q); setSearch(next.q);
    setPage(next.page); setPageSize(next.size);
    setUndated(next.undated); setDates(next.dates);
    setTypes(next.types); setFolders(next.folders); setJobRun(next.run); setOpenId(next.photo);
    setMatchState({ photo: next.photo, view: next.match });
    setInspectorTab(next.inspectorTab);
    setComparison(next.comparison); setComparisonNavigation(n => n + 1);
    setLocate(restoringReview.current || next.photo == null ? null : { id: next.photo, delta: 0 }); setRevealId(null);
    if (next.folders.length || next.dates.length) setBrowseBy(initialBrowseBy(next.folders, next.dates));
    // A link names normal results, not the transient selection/review view.
    // Keep the explicit selection available to the user after navigating.
    setFocus(null); setPendingJump(null); setNoticeState(null); setActionError(null);
  });
  const [refreshKey, setRefreshKey] = useState(0);
  const [closedIndexSummary, setClosedIndexSummary] = useState<string | null>(() => {
    try { return localStorage.getItem("ns.closedIndexSummary"); } catch { return null; }
  });
  const summaryToggle = useRef<HTMLButtonElement>(null);
  const [previewSummaryExpanded, setPreviewSummaryExpanded] = useState(false);
  useEffect(() => { setPreviewSummaryExpanded(false); }, [openId]);
  const toggleIndexSummary = (key: string | null) => {
    setClosedIndexSummary(key);
    try {
      if (key == null) localStorage.removeItem("ns.closedIndexSummary");
      else localStorage.setItem("ns.closedIndexSummary", key);
    } catch { /* Dismissal still works for this visit without storage. */ }
    requestAnimationFrame(() => summaryToggle.current?.focus({ preventScroll: true }));
  };
  useEffect(() => { setRefreshKey(n => n + 1); }, [status]);
  useEffect(() => {
    const update = () => setRefreshKey(n => n + 1);
    window.addEventListener("ns-review-changed", update);
    return () => window.removeEventListener("ns-review-changed", update);
  }, []);
  useEffect(() => {
    const photo = noticePhoto.current;
    if (photo == null) return;
    let live = true;
    api.inspect(photo).then((d) => {
      if (live && noticePhoto.current === photo && !["Rejected", "Rejected_Copied"].includes(d.status)) setNotice(null);
    }, () => undefined);
    return () => { live = false; };
  }, [refreshKey]);
  // What each action would take of the selection, for the selection bar.
  const [selectionActions, setSelectionActions] = useState<SelectionCounts>(NO_ACTIONS);
  const [dismissedId, dismissRun] = useDismissedRun();
  const { jobs, connection } = useJobFeed();
  const submission = useSyncExternalStore(subscribeSubmission, submissionSnapshot);
  const jobRunning = !!submission.pending || (jobs.active != null && jobs.active.presented_status !== "Interrupted");
  // The job whose photos are shown, for the line above them; read again as jobs end.
  const [jobInfo, setJobInfo] = useState<Run | null>(null);
  const lastStatus = jobs.last ? `${jobs.last.id}:${jobs.last.status}` : "";
  useEffect(() => {
    let live = true;
    if (jobRun == null) { setJobInfo(null); return; }
    api.run(jobRun).then((r) => live && setJobInfo(r), () => live && setJobInfo(null));
    return () => { live = false; };
  }, [jobRun, lastStatus]);
  const header = useRef<HTMLElement>(null);
  const content = useRef<HTMLElement>(null);
  const [contentWidth, setContentWidth] = useState(window.innerWidth);
  useLayoutEffect(() => {
    const el = content.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setContentWidth(el.clientWidth));
    observer.observe(el);
    setContentWidth(el.clientWidth);
    return () => observer.disconnect();
  }, []);
  const [panelWidth, setPanelWidth] = useState<number | null>(() => {
    try { return Number(localStorage.getItem("ns.inspectorWidth")) || null; } catch { return null; }
  });
  // The left panel's width: folder paths can be wide, so it can be dragged wider.
  const side = useRef<HTMLElement>(null);
  const [sideWidth, setSideWidthState] = useState<number | null>(() => {
    try {
      const saved = Number(localStorage.getItem("ns.sideWidth"));
      return Number.isFinite(saved) && saved > 0 ? Math.min(SIDE_MAX, Math.max(SIDE_MIN, saved)) : null;
    } catch { return null; }
  });

  useHeaderHeight(header);

  // A finished job changes the catalog: refresh the view and the counts. Keyed on
  // the last finished run rather than on seeing a job stop, because a job shorter
  // than one feed update is never seen running at all. The first value seen is the
  // baseline even when there is no finished run yet, so the very first job on a new
  // catalog still refreshes the view.
  const lastFinished = jobs.last && !jobRunning ? `${jobs.last.id}:${jobs.last.status}` : null;
  const seenFinished = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (seenFinished.current !== undefined && lastFinished != null && seenFinished.current !== lastFinished) {
      setRefreshKey((k) => k + 1);
      refreshStatus();
    }
    seenFinished.current = lastFinished;
  }, [lastFinished, refreshStatus]);

  // Only a changed search goes back to page 1; loading the page keeps the URL's page.
  useEffect(() => {
    const t = window.setTimeout(() => {
      if (search.trim() !== q) { setQ(search.trim()); setPage(1); }
    }, 300);
    return () => window.clearTimeout(t);
  }, [search, q]);

  useEffect(() => {
    const p = new URLSearchParams();
    p.set("view", view);
    if (similar) { p.set("similar", "1"); p.set("group_sets", groupSets ? "1" : "0"); }
    if (suspicious) p.set("suspicious", "1");
    if (reason !== "all") p.set("reason", reason);
    if (reviewPhoto != null) p.set("review_photo", String(reviewPhoto));
    p.set("sort", sort);
    if (similar) p.set("match_min", String(matchMin));
    if (q) p.set("q", q);
    if (page > 1) p.set("page", String(page));
    if (pageSize !== PAGE_SIZES[0]) p.set("size", String(pageSize));
    if (undated) p.set("undated", "1");
    dates.forEach((d) => p.append("date", d));
    types.forEach((t) => p.append("type", t));
    folders.forEach((f) => p.append("folder", f));
    if (jobRun != null) p.set("run", String(jobRun));
    if (openId != null) {
      p.set("photo", String(openId));
      if (comparison?.origin === openId) p.set("review", JSON.stringify(comparison));
      if (inspectorTab === "similar" || matchView) p.set("tab", inspectorTab);
      if (matchView) {
        p.set("match", String(matchView.threshold));
        if (matchView.page > 1) p.set("match_page", String(matchView.page));
      }
    }
    const url = `${window.location.pathname}${p.size ? `?${p}` : ""}`;
    window.history.replaceState(null, "", url);
    rememberLibraryQuery(p.toString());
  }, [similar, groupSets, suspicious, reason, view, sort, matchMin, q, page, pageSize, undated, dates, types, folders, jobRun, openId, matchView, inspectorTab, comparison, reviewPhoto]);

  const results = usePaged((p) => api.photos({ view: browseView, similar, suspicious, reason: reviewFilter, run: jobRun ?? undefined, sort: browseSort, match_min: galleryMinimum, group_sets: grouped, q, page: p, page_size: pageSize, undated, dates, types, folders }),
                           JSON.stringify([similar, suspicious, reason, browseView, jobRun, browseSort, galleryMinimum, grouped, q, undated, dates, types, folders]), jump, pageSize, refreshKey, setLoadError);
  const data: PhotoPage | null = results.meta;
  // The Rejects view sees an emptied file first; the reminder follows it.
  const rejectsShown = browseView === "rejects" ? data?.rejects?.photos : undefined;
  useEffect(() => {
    if (rejectsShown != null && rejectsShown !== status.rejects?.photos) refreshStatus();
  }, [rejectsShown]);

  // The tree's counts ignore its own filter, so an unticked month keeps its number;
  // jumping needs the filtered months, to land on the right page.
  useEffect(() => {
    let live = true;
    api.timeline({ view: browseView, similar, suspicious, reason: reviewFilter, run: jobRun ?? undefined, match_min: galleryMinimum, q, undated, types, folders }).then((t) => live && setTimeline(t), () => live && setTimeline(null));
    return () => { live = false; };
  }, [similar, suspicious, reason, browseView, jobRun, galleryMinimum, grouped, q, undated, types, folders, refreshKey]);
  useEffect(() => {
    let live = true;
    if (dates.length === 0) { setJumpTimeline(null); return; }
    api.timeline({ view: browseView, similar, suspicious, reason: reviewFilter, run: jobRun ?? undefined, match_min: galleryMinimum, group_sets: grouped, q, undated, dates, types, folders }).then((t) => live && setJumpTimeline(t), () => live && setJumpTimeline(null));
    return () => { live = false; };
  }, [similar, suspicious, reason, browseView, jobRun, galleryMinimum, grouped, q, undated, dates, types, folders, refreshKey]);
  // The Types section's counts follow the view, search, dates and folders, never its own filter.
  useEffect(() => {
    let live = true;
    const ids = [...selected];
    if (ids.length === 0) setSelectionActions(NO_ACTIONS);
    else api.selection(ids, "newest", 1, 1, galleryMinimum)
      .then((s) => live && setSelectionActions(s.actions ?? NO_ACTIONS), () => live && setSelectionActions(NO_ACTIONS));
    return () => { live = false; };
  }, [selected, galleryMinimum, refreshKey]);
  useEffect(() => {
    let live = true;
    api.types({ view: browseView, similar, suspicious, reason: reviewFilter, run: jobRun ?? undefined, match_min: galleryMinimum, q, undated, dates, folders }).then((t) => live && setTypeCounts(t.types), () => live && setTypeCounts(null));
    return () => { live = false; };
  }, [similar, suspicious, reason, browseView, jobRun, galleryMinimum, grouped, q, undated, dates, folders, refreshKey]);
  // The Folders tree's counts follow the view, search, dates and types, never its own
  // filter; the ticked folders are sent so they stay listed at 0.
  useEffect(() => {
    let live = true;
    api.folders({ view: browseView, similar, suspicious, reason: reviewFilter, run: jobRun ?? undefined, match_min: galleryMinimum, q, undated, dates, types, folders }).then((t) => live && setFolderTree(t), () => live && setFolderTree(null));
    return () => { live = false; };
  }, [similar, suspicious, reason, browseView, jobRun, galleryMinimum, grouped, q, undated, dates, types, folders, refreshKey]);

  const memberBrowse = focus?.kind === "set" ? { view: "all" as const, q: "", undated: false,
    set_reference: focus.reference!, match_min: focus.threshold!, dates: [], types: [], folders: [] } : null;
  const setBrowse = useMemo(() => grouped && exploreReference == null ? ({ view, similar, suspicious, reason: reviewFilter, sort, match_min: galleryMinimum,
    group_sets: true, q, undated, dates, types, folders, page_size: pageSize }) : undefined,
    [similar, suspicious, reason, grouped, exploreReference, view, sort, galleryMinimum, q, undated, dates, types, folders, pageSize, refreshKey]);
  const showSet = (reference: number, threshold: number) => {
    setComparison(null); setExploreReference(null); setOpenId(null); setLocate(null); setRevealId(null);
    setFocus({ kind: "set", ids: [], reference, threshold }); setFocusPage(1);
  };
  const focused = usePaged((p) => (memberBrowse ? api.photos({ ...memberBrowse, sort, page:p, page_size:pageSize }).then(r => ({...r, missing: []}))
                                        : focus ? api.selection(focus.ids, sort, p, pageSize, galleryMinimum)
                                          : Promise.resolve({ items: [], total: 0, page: p, page_size: pageSize, missing: [] } as SelectionPage)),
                           JSON.stringify([focus, sort, galleryMinimum]), focusJump, pageSize, refreshKey, setLoadError);
  const focusData: SelectionPage | null = focus ? focused.meta : null;
  // The photo kept in Keep this one, reject the rest, loaded on its own so it leads the
  // review whatever the sort or page.
  const [keptItem, setKeptItem] = useState<PhotoItem | null>(null);
  const keepId = focus?.kind === "review" ? focus.keep : undefined;
  useEffect(() => {
    let live = true;
    setKeptItem(null);
    if (keepId != null) api.selection([keepId], "newest", 1, 1, galleryMinimum)
      .then((s) => { if (live) setKeptItem(s.items[0] ?? null); }, () => undefined);
    return () => { live = false; };
  }, [keepId, galleryMinimum, refreshKey]);
  const gallerySummary = focus ? focusData : data;

  // What the gallery shows: the results, or only the selection. Every loaded page in
  // order, each photo tagged with its page so scrolling can say which page is on top.
  const list = focus ? focused : results;
  const visible = focus ? focusPage : page;
  const flat = useMemo(() => {
    const items: PhotoItem[] = [];
    const pageOf: number[] = [];
    for (const p of [...list.pages.keys()].sort((a, b) => a - b)) {
      for (const item of list.pages.get(p) ?? []) { items.push(item); pageOf.push(p); }
    }
    return { items, pageOf };
  }, [list.pages]);
  // Explicit navigation resolves one rank on the server; ordinary gallery clicks
  // and later manual scrolling never continually track the open Inspector photo.
  useEffect(() => {
    if (!locate) return;
    let live = true;
    api.photoPosition({ photo_id: locate.id, view: browseView, similar, suspicious, reason: reviewFilter, run: jobRun ?? undefined, sort: browseSort, match_min: galleryMinimum, group_sets: grouped, q, undated, dates, types, folders,
                        ...(memberBrowse ?? {}), page_size: pageSize, ids: memberBrowse ? undefined : focus?.ids }).then((found) => {
      if (!live) return;
      setLocate(null);
      setNotice(null);
      if (found.position == null) {
        setNotice("This photo is outside the current gallery results.", [{ label: "Show in gallery", run: () => {
          setNotice(null); setFocus({ kind: "photo", ids: [locate.id] }); setFocusPage(1); setRevealId(locate.id);
        } }]);
        return;
      }
      const id = locate.delta < 0 ? found.previous_id : locate.delta > 0 ? found.next_id : locate.id;
      if (id == null) return;
      setOpenId(id);
      setRevealId(id);
      if (!flat.items.some(item => item.id === id)) {
        const destination = Math.floor((found.position + locate.delta) / pageSize) + 1;
        if (focus) setFocusPage(destination); else setPage(destination);
      }
    }, () => {
      if (!live) return;
      setLocate(null);
      setNotice("The photo's gallery position could not be loaded.", [
        { label: "Retry locating photo", run: () => setLocate({ ...locate }) }]);
    });
    return () => { live = false; };
  }, [similar, suspicious, reason, locate, view, sort, galleryMinimum, grouped, q, undated, dates, types, folders, pageSize, focus, refreshKey]);

  useEffect(() => {
    if (revealId == null || !list.ready || !flat.items.some(item => item.id === revealId)) return;
    const frame = requestAnimationFrame(() => {
      const card = document.querySelector<HTMLElement>(`.grid .card[data-id="${revealId}"]`);
      if (!card) return;
      const box = card.getBoundingClientRect();
      const top = Math.max(0, header.current?.getBoundingClientRect().bottom ?? 0) + 12;
      if (box.top < top || box.bottom > window.innerHeight) {
        window.scrollTo({ top: Math.max(0, window.scrollY + box.top - top), behavior: "instant" });
      }
      setRevealId(null);
    });
    return () => cancelAnimationFrame(frame);
  }, [revealId, flat, list.ready]);

  useEffect(() => {
    const cancel = () => { setLocate(null); setRevealId(null); };
    window.addEventListener("wheel", cancel, { passive: true });
    window.addEventListener("touchmove", cancel, { passive: true });
    return () => { window.removeEventListener("wheel", cancel); window.removeEventListener("touchmove", cancel); };
  }, []);
  // The photos on screen, for Select all on screen; until first measured, the page.
  const screenItems = useMemo(() => {
    const ids = new Set(onScreen);
    const found = flat.items.filter((i) => ids.has(i.id));
    return found.length ? found : list.pages.get(visible) ?? [];
  }, [flat, onScreen, list.pages, visible]);
  const pages = list.meta ? Math.max(1, Math.ceil(list.meta.total / pageSize)) : 1;
  // "Outside this view": selected photos not among the results loaded on screen.
  const loadedIds = useMemo(() => new Set([...results.pages.values()].flat().map((i) => i.id)), [results.pages]);
  const outside = [...selected].filter((id) => !loadedIds.has(id)).length;
  // Every month with a photo on screen, highlighted in the tree. Photos, not pages: a
  // month with a few photos rarely starts a page or a row, and was skipped.
  const currentDates = useMemo(() => {
    if (sort !== "newest" && sort !== "oldest") return [];
    const dateOf = new Map<number, string | null>();
    for (const items of results.pages.values()) for (const i of items) dateOf.set(i.id, i.date_taken);
    const ids = onScreen.length ? onScreen : (results.pages.get(page) ?? []).slice(0, 1).map((i) => i.id);
    return [...new Set(ids.map((id) => dateOf.get(id)?.slice(0, 7)).filter((m): m is string => !!m))];
  }, [results.pages, onScreen, page, sort]);

  // Continuous scrolling: load the next page as the end nears, and the previous one as
  // the start does, keeping the photos on screen where they are.
  const topSentinel = useRef<HTMLDivElement>(null);
  const bottomSentinel = useRef<HTMLDivElement>(null);
  const prepend = useRef<{ height: number; y: number } | null>(null);
  useEffect(() => {
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (locate || revealId != null) continue;
        if (!entry.isIntersecting) continue;
        if (entry.target === bottomSentinel.current) list.load(list.last + 1);
        if (entry.target === topSentinel.current && list.first > 1 && !prepend.current) {
          prepend.current = { height: document.documentElement.scrollHeight, y: window.scrollY };
          list.load(list.first - 1);
        }
      }
    }, { rootMargin: "800px 0px" });
    if (topSentinel.current) observer.observe(topSentinel.current);
    if (bottomSentinel.current) observer.observe(bottomSentinel.current);
    return () => observer.disconnect();
  }, [list.first, list.last, list.load, list.ready, focus, locate, revealId]);
  useEffect(() => { if (list.failures.has(list.first - 1)) prepend.current = null; }, [list.failures, list.first]);
  useLayoutEffect(() => {
    const mark = prepend.current;
    if (!mark) return;
    prepend.current = null;
    window.scrollTo(0, mark.y + document.documentElement.scrollHeight - mark.height);
  }, [list.first]);
  // The page on top follows the scroll: the page of the first photo below the header.
  useEffect(() => {
    let frame = 0;
    const onScroll = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const top = header.current?.getBoundingClientRect().bottom ?? 0;
        const bottom = window.innerHeight;
        let first: HTMLElement | null = null;
        const seen: number[] = [];
        for (const card of document.querySelectorAll<HTMLElement>(".grid .card[data-page]")) {
          const box = card.getBoundingClientRect();
          if (box.bottom <= top + 4) continue;
          if (box.top >= bottom) break;
          first ??= card;
          seen.push(Number(card.dataset.id));
        }
        if (!first) return;
        const p = Number(first.dataset.page);
        if (focus) setFocusVisible(p); else setVisiblePage(p);
        setOnScreen(seen);
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    // The gallery also changes width without a window resize: the photo panel opening or
    // closing reflows the grid, and what is on screen with it.
    const pane = document.querySelector(".gallery-pane");
    const observer = pane ? new ResizeObserver(onScroll) : null;
    if (pane) observer!.observe(pane);
    return () => { window.removeEventListener("scroll", onScroll); window.removeEventListener("resize", onScroll);
                   observer?.disconnect(); cancelAnimationFrame(frame); };
  }, [focus]);
  // Photos arriving change what is on screen without a scroll: measure again.
  useEffect(() => { window.dispatchEvent(new Event("resize")); }, [flat]);
  // A jump starts at the top of the page it lands on.
  useEffect(() => { if (jump.n > 0) window.scrollTo(0, 0); }, [jump.n]);
  useEffect(() => { if (focusJump.n > 0) window.scrollTo(0, 0); }, [focusJump.n]);

  const showSelected = () => { setFocus({ kind: "selection", ids: [...selected] }); setFocusPage(1); };
  const backToResults = () => { setFocus(null); setFocusPage(1); };
  // Clearing the selection leaves nothing to show only, so it returns to the results.
  const clearSelection = () => { setSelected(new Set()); if (focus?.kind === "selection" || focus?.kind === "review") backToResults(); };

  const changeDates = (next: string[]) => { setDates(next); setPage(1); };
  const changeTypes = (next: string[]) => { setTypes(next); setPage(1); };
  const changeFolders = (next: string[]) => { setFolders(next); setPage(1); };
  // All photos clears the other filters, but every tile preserves the search.
  const narrowed = reason !== "all" || undated || dates.length > 0 || types.length > 0 || folders.length > 0 || !!q;
  const sortChoices = useRef<Partial<Record<View, Sort>>>({});
  const chooseMatchMinimum = (value: number) => {
    savePreference("ns.matchMin", String(value));
    setMatchMin(value); setPage(1);
  };
  const chooseSort = (value: Sort) => {
    const scope: View = similar ? "similar" : view;
    sortChoices.current[scope] = value;
    savePreference(`ns.sort.${scope}`, value);
    setSort(value); setPage(1); setFocusPage(1);
  };
  // A job's photos open unfiltered, so none of them is hidden by a filter left on; Back to
  // results puts the filters back. A view button leaves the job with the filters as they are.
  const jobFilters = useRef<{ q: string; similar: boolean; suspicious: boolean; reason: string; undated: boolean; dates: string[]; types: string[]; folders: string[] } | null>(null);
  useEffect(() => {
    if (followJob == null || jobs.active || jobs.last?.id !== followJob) return;
    setFollowJob(null);
    if (jobRun != null) { setJobRun(followJob); setPage(1); }
  }, [followJob, jobs.active, jobs.last?.id]);
  const showJob = (id: number) => {
    if (jobRun == null) jobFilters.current = { q, similar, suspicious, reason, undated, dates, types, folders };
    setFocus(null); setJobRun(id); setSimilar(false); setSuspicious(false); setReason("all");
    setQ(""); setSearch(""); setUndated(false); setDates([]); setTypes([]); setFolders([]); setPage(1);
  };
  const leaveJob = () => {
    setFollowJob(null);
    const was = jobFilters.current;
    jobFilters.current = null;
    setJobRun(null);
    if (was) { setSimilar(was.similar); setSuspicious(was.suspicious); setReason(was.reason); setQ(was.q); setSearch(was.q); setUndated(was.undated); setDates(was.dates); setTypes(was.types); setFolders(was.folders); }
    setPage(1);
  };
  const openNeedsReview = (item: PhotoItem) => {
    const top = header.current?.getBoundingClientRect().bottom ?? 0;
    const cards = [...document.querySelectorAll<HTMLElement>(".grid .card[data-id]")];
    const anchor = cards.find(c => c.getBoundingClientRect().bottom > top);
    const entry = new URLSearchParams(window.location.search);
    if (anchor?.dataset.page) entry.set("page", anchor.dataset.page);
    setReviewReturn({ url: `${window.location.pathname}?${entry}`,
      anchor: Number(anchor?.dataset.id ?? item.id), offset: anchor?.getBoundingClientRect().top ?? top, opener: item.id });
    const notes = item.review?.reasons ?? [];
    const reason = notes.length === 1 ? notes[0].reason : "all";
    // Library browsing restrictions must not hide a photo in its decision inbox.
    navigate(`/?view=review&reason=${reason}&photo=${item.id}&review_photo=${item.id}`);
  };
  const backToLibrary = () => {
    if (!reviewReturn) return;
    restoringReview.current = reviewReturn;
    navigate(reviewReturn.url);
    setReviewReturn(null);
    setRefreshKey(n => n + 1);
  };
  useLayoutEffect(() => {
    const saved = restoringReview.current;
    if (!saved || !list.ready || view !== "organized") return;
    const anchor = document.querySelector<HTMLElement>(`.grid .card[data-id="${saved.anchor}"]`);
    if (anchor) window.scrollBy(0, anchor.getBoundingClientRect().top - saved.offset);
    else window.scrollTo(0, 0); // The anchor may have been rejected during review.
    const opener = document.querySelector<HTMLElement>(`.grid .card[data-id="${saved.opener}"]`);
    (opener?.querySelector<HTMLElement>(".review-card-notes a") ?? opener?.querySelector<HTMLElement>(".card-image"))?.focus({ preventScroll: true });
    restoringReview.current = null;
  }, [list.ready, flat, view]);
  const chooseView = (v: View) => {
    setJobRun(null); jobFilters.current = null; setFollowJob(null);
    sortChoices.current[similar ? "similar" : view] = sort;
    setView(v);
    setOpenId(null); setLocate(null); setRevealId(null); setComparison(null); setReviewPhoto(null);
    const scope: View = similar && (v === "organized" || v === "review") ? "similar" : v;
    setSort(sortChoices.current[scope] ?? savedSort(scope));
    setPage(1);
    if (v === "unorganized" || v === "rejects") setSimilar(false);
    if (v !== "review" && (v !== "organized" || reason !== "small")) setReason("all");
    if (v === "all") { setUndated(false); setDates([]); setTypes([]); setFolders([]); }
  };
  const jumpTo = (key: string) => {
    const newestFirst = sort !== "oldest";
    const target = datePage(jumpTimeline ?? timeline ?? { months: [], undated: 0 }, newestFirst, pageSize, key);
    if (target == null) {
      const then = (next: string[]) => () => { setNotice(null); changeDates(next); setPendingJump(key); };
      setNotice(`${dateLabel(key)} is outside the dates shown.`, [
        { label: `Show ${dateLabel(key)} too`, run: then([...dates, key]) },
        { label: "Show all dates", run: then([]) },
      ]);
      return;
    }
    if (sort !== "newest" && sort !== "oldest") {
      setSort("newest");
      setNotice("Sorted newest first, so the gallery can go to a date.");
    } else {
      setNotice(null);
    }
    setPage(target);
  };

  // Go to the date once the filtered months that include it have arrived.
  useEffect(() => {
    if (!pendingJump) return;
    const source = dates.length ? jumpTimeline : timeline;
    const has = (m: string) => m === pendingJump || m.startsWith(`${pendingJump}-`);
    if (source && (source.months.some((m) => has(m.month)) || (pendingJump === "none" && source.undated > 0))) {
      setPendingJump(null);
      jumpTo(pendingJump);
    }
  }, [pendingJump, jumpTimeline, timeline, dates]);

  const changePageSize = (size: number) => {
    // Keep the first photo on screen in view: land on the page that holds it.
    const first = ((focus ? focusPage : page) - 1) * pageSize;
    setPageSize(size);
    if (focus) setFocusPage(Math.floor(first / size) + 1);
    else setPage(Math.floor(first / size) + 1);
  };

  // Adding photos needs their place; callers pass only photos of the selection's place.
  const toggleIds = (ids: number[], on: boolean, idsPlace?: Place) => {
    if (on && idsPlace) setPlace((cur) => cur ?? idsPlace);
    setSelected((cur) => {
      const next = new Set(cur);
      for (const id of ids) { if (on) next.add(id); else next.delete(id); }
      return next;
    });
  };
  // Ticking keeps to the selection's place; with nothing selected, the first photo sets it.
  const toggleMany = (items: PhotoItem[], on: boolean) => {
    if (!on) { toggleIds(items.map((i) => i.id), false); return; }
    const target = place ?? (items.length ? placeOf(items[0].status) : null);
    if (!target) return;
    toggleIds(items.filter((i) => placeOf(i.status) === target).map((i) => i.id), true, target);
  };
  const toggle = (item: PhotoItem, on: boolean) => toggleMany([item], on);
  // Select all takes one place: the selection's, else the library's if any are shown. It
  // says how many of the other place it left out.
  const selectAll = async () => {
    try {
      const got = focus && !memberBrowse
        ? { ids: focus.ids, in_rejects: (await api.selection(focus.ids, "newest", 1, 1, galleryMinimum)).in_rejects ?? [] }
        : await api.photoIds(memberBrowse ?? { view: browseView, similar, suspicious, reason: reviewFilter, run: jobRun ?? undefined, match_min: galleryMinimum, group_sets: grouped, q, undated, dates, types, folders });
      const rejected = new Set(got.in_rejects);
      const library = got.ids.filter((id) => !rejected.has(id));
      const target: Place = place ?? (library.length > 0 ? "library" : "rejects");
      const take = target === "library" ? library : got.ids.filter((id) => rejected.has(id));
      toggleIds(take, true, target);
      const left = got.ids.length - take.length;
      if (left > 0) setNotice(`${target === "library" ? plural(left, "photo in Rejects was", "photos in Rejects were")
        : plural(left, "library photo was", "library photos were")} left out: photos in Rejects and library photos can't be selected together.`);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "The photos could not be selected.");
    }
  };

  const step = useCallback((delta: number) => {
    if (openId == null) return;
    const index = flat.items.findIndex((i) => i.id === openId);
    const next = flat.items[index + delta];
    if (index >= 0 && next) { setOpenId(next.id); setRevealId(next.id); setLocate(null); }
    else { setLocate({ id: openId, delta }); setRevealId(null); }
  }, [flat, openId]);

  // The divider between the gallery and the Inspector: drag it, or focus it and use
  // the arrow keys. Filters keep their width and the photo grid keeps MIN_GALLERY.
  // Clamp restored preferences too, and recalculate when the window or filters resize.
  const inspectorMax = Math.max(MIN_SIDE,
    contentWidth - (focus ? 0 : (sideWidth ?? 240) + 8) - MIN_GALLERY - 8);
  const boundedWidth = (px: number) => Math.round(Math.min(inspectorMax, Math.max(MIN_SIDE, px)));
  const effectivePanelWidth = boundedWidth(Number.isFinite(panelWidth) && panelWidth != null ? panelWidth : contentWidth / 2);
  const setWidth = (px: number) => {
    const clamped = boundedWidth(px);
    setPanelWidth(clamped);
    try { localStorage.setItem("ns.inspectorWidth", String(clamped)); } catch { /* per-viewer convenience only */ }
  };
  const drag = (e: ReactPointerEvent) => {
    e.preventDefault();
    const right = content.current?.getBoundingClientRect().right ?? window.innerWidth;
    const move = (ev: PointerEvent) => setWidth(right - ev.clientX);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.classList.remove("dragging");
    };
    document.body.classList.add("dragging");
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  const currentWidth = () => effectivePanelWidth;

  const start = (mode: "index" | ActionMode, fileIds?: number[]) => async () => {
    setActionError(null);
    try {
      const run = await api.startJob(fileIds ? { mode, file_ids: fileIds } : { mode });
      if (fileIds) {
        // Back where the user was (webui-spec 2, after a job): the review or the selection
        // shown closes; the finished banner opens the job's photos.
        setSelected(new Set());
        setFocus((cur) => (cur && (cur.kind === "review" || cur.kind === "selection") ? null : cur));
        // Started from a job's photos: they follow to this job once it ends.
        if (jobRun != null && run.id != null) setFollowJob(run.id);
      }
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "The job could not be started.");
    }
  };

  // A single photo confirms in place. Multiple photos need a review where the
  // full selection can be scrolled, opened and unticked before committing.
  // The review holds only the photos the action takes; the rest are counted, not shown,
  // so a Reject never offers photos it would skip.
  const transferSelected = async (mode: ActionMode) => {
    if (selected.size === 1) {
      askTransfer(mode, [...selected], undefined, undefined, place === "rejects");
      return;
    }
    setActionError(null);
    try {
      const ids = [...selected];
      const takes = (await api.selection(ids, "newest", 1, 1, galleryMinimum, mode)).takes ?? ids;
      setFocus({ kind: "review", mode, ids: takes, leftOut: ids.length - takes.length });
      setFocusPage(1);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "The selected photos could not be checked.");
    }
  };
  const reviewIds = focus?.kind === "review" ? focus.ids.filter((id) => selected.has(id)) : [];
  const review = focus?.kind === "review" && focus.mode ? transferConfirm(focus.mode, status, reviewIds, start(focus.mode, reviewIds), undefined, undefined, place === "rejects") : null;
  const [committing, setCommitting] = useState(false);
  const commit = async () => {
    if (!review) return;
    setCommitting(true);
    try { await review.run(); } finally { setCommitting(false); }
  };

  const askTransfer = (mode: ActionMode, ids?: number[], onCancel?: () => void, filename?: string, inRejects = false) =>
    setConfirm(transferConfirm(mode, status, ids, start(mode, ids), onCancel, filename, inRejects));
  // Keep this one, reject the rest (webui-spec 7.8): every look-alike of the kept photo at
  // the threshold, reviewed before anything moves, the kept photo shown first and never ticked.
  const keepAndReview = async (keep: number, keepName: string, threshold: number) => {
    setActionError(null);
    try {
      const set = await api.photoIds({ view: "all", q: "", undated: false, set_reference: keep, match_min: threshold,
                                       dates: [], types: [], folders: [] });
      // Look-alikes already in Rejects are not rejected again, and a selection holds one place.
      const rejected = new Set(set.in_rejects);
      const rest = set.ids.filter((id) => id !== keep && !rejected.has(id));
      setComparison(null); setOpenId(null); setLocate(null); setRevealId(null);
      setSelected(new Set(rest));
      setPlace("library");
      setFocus({ kind: "review", mode: "reject", ids: rest, keep, keepName });
      setFocusPage(1);
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "The look-alikes could not be loaded.");
    }
  };
  // A folder's Copy or Move: the engine takes the folder itself (--source-subdir), and
  // Retry offers the same folder again.
  const folderShown = shownFolder(folderTree, folders);
  const askFolder = (mode: ActionMode) => {
    if (!folderShown) return;
    setConfirm(transferConfirm(mode, status, { folder: folderLabel(folderShown.path) }, async () => {
      setActionError(null);
      try {
        await api.startJob({ mode, source_subdir: folderShown.path });
      } catch (e) {
        setActionError(e instanceof ApiError ? e.message : "The job could not be started.");
      }
    }));
  };

  // The divider right of the left panel: drag it, or focus it and use the arrow keys.
  const setSideWidth = (px: number) => {
    const clamped = Math.round(Math.min(Math.max(px, SIDE_MIN), SIDE_MAX));
    setSideWidthState(clamped);
    try { localStorage.setItem("ns.sideWidth", String(clamped)); } catch { /* per-viewer convenience only */ }
  };
  const dragSide = (e: ReactPointerEvent) => {
    e.preventDefault();
    const left = side.current?.getBoundingClientRect().left ?? 0;
    const move = (ev: PointerEvent) => setSideWidth(ev.clientX - left);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.classList.remove("dragging");
    };
    document.body.classList.add("dragging");
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  const currentSide = () => sideWidth ?? side.current?.getBoundingClientRect().width ?? 240;

  const noPhotos = status.photos === 0;
  const filterCount = (n: number) => <span className="filter-count" style={{ minWidth: `${count(status.photos).length + 2}ch` }}>({count(n)})</span>;

  const screenSelected = screenItems.filter((i) => selected.has(i.id)).length;
  const onPager = focus ? setFocusPage : setPage;
  const galleryNoun = grouped ? "set" : view === "unorganized" && (data?.index_summary?.failed ?? 0) > 0 ? "file" : "photo";
  const indexSummaryKey = JSON.stringify(data?.index_summary?.last_index ?? null);
  const indexSummaryClosed = closedIndexSummary === indexSummaryKey || (openId != null && !previewSummaryExpanded);
  const indexNeedsAttention = !!data?.index_summary && data.index_summary.failed === data.index_summary.photos
    && data.index_summary.failed > 0;

  return (
    <div className={`app ${openId != null ? "with-inspector" : ""}`}>
      <header className="toolbar" ref={header}>
        <div className="toolbar-row">
          <h1 className="brand"><Logo />NegativeSpace</h1>
          <PageNavigation active="library" jobs={<JobsMenu
              state={{ jobRunning, noPhotos, eligible: status.eligible, copied: status.copied,
                       folder: folderShown ? { name: folderLabel(folderShown.path), eligible: folderShown.eligible } : null,
                       folders: folders.length }}
              onIndex={start("index")}
              onTransfer={(mode, scope) => (scope === "folder" ? askFolder(mode) : askTransfer(mode))} />} />
          {selected.size > 0 && (
            <SelectionBar selected={selected.size} outside={outside} focused={!!focus} reviewing={focus?.kind === "review"}
                          counts={selectionActions} place={place} jobRunning={jobRunning} onAction={transferSelected}
                          onShowSelected={showSelected} onBack={backToResults} onClear={clearSelection} />
          )}
          <PageTools version={status.version} onOpenSettings={onOpenSettings} />
        </div>
        <div className={`toolbar-row toolbar-browse ${focus ? "is-muted" : ""}`}>
          <button className="dates-toggle" aria-expanded={datesOpen} onClick={() => setDatesOpen(!datesOpen)}>
            Browse{dates.length + types.length + folders.length ? ` (${dates.length + types.length + folders.length})` : ""}
          </button>
          <nav className="views" aria-label="Views">
            {PLACE_VIEWS.map((v) => (
              <button key={v} aria-pressed={jobRun == null && v === view} className={jobRun == null && v === view && !(v === "all" && narrowed) ? "active" : ""} disabled={!!focus}
                      onClick={() => chooseView(v)}>
                <span title={v === "similar" ? `Destination photos with at least one visual match at ${galleryMinimum}% or higher` : undefined}>{VIEW_LABEL[v]}</span> <span className="view-count">{data ? `(${count(data.matches[v])})` : ""}</span>
              </button>
            ))}
          </nav>
          <div className="browse-search">
            <SearchField className="search" placeholder="Search filenames" value={search} disabled={!!focus}
                         onValueChange={setSearch} aria-label="Search filenames" />
            <select value={browseSort} onChange={(e) => { chooseSort(e.target.value as Sort); }} aria-label="Sort">
              <option value="newest">Newest first</option>
              <option value="oldest">Oldest first</option>
              <option value="largest">Largest first</option>
              <option value="smallest">Smallest first</option>
              <option value="name">Name</option>
              {similar && jobRun == null && <option value="matches">Most matches first</option>}
            </select>
          </div>
        </div>
        <div className="review-chips" role="group" aria-label={view === "review" ? "Review reason" : "Filter photos"}>
          {(view === "organized" || view === "review") && <button aria-pressed={similar} disabled={!!focus} className={similar ? "active" : ""} onClick={() => { setSimilar(!similar); setPage(1); const scope: View = !similar ? "similar" : view; setSort(sortChoices.current[scope] ?? savedSort(scope)); }}>Has similar photos {filterCount(data?.chips?.similar ?? 0)}</button>}
          <button aria-pressed={suspicious} disabled={!!focus} className={suspicious ? "active" : ""} onClick={() => { setSuspicious(!suspicious); setPage(1); }}>Suspicious dates {filterCount(data?.chips?.suspicious ?? 0)}</button>
          <button aria-pressed={undated} disabled={!!focus} className={undated ? "active" : ""} onClick={() => { setUndated(!undated); setPage(1); }}>No capture date {filterCount(data?.chips?.undated ?? 0)}</button>
          {(view === "organized" || view === "review") && <button disabled={!!focus} aria-pressed={reason === "small"}
            className={reason === "small" ? "active" : ""} onClick={() => { setReason(reason === "small" ? "all" : "small"); setPage(1); }}>Small images {filterCount(data?.chips?.small ?? 0)}</button>}
          {view === "review" && <button disabled={!!focus} aria-pressed={reason === "later"}
            className={reason === "later" ? "active" : ""} onClick={() => { setReason(reason === "later" ? "all" : "later"); setPage(1); }}>Review later {filterCount(data?.reasons?.later ?? 0)}</button>}
        </div>
        <JobDrawer jobs={jobs} connection={connection} />
        <FinishedBanner jobs={jobs} dismissedId={dismissedId} onDismiss={dismissRun}
                        onShowPhotos={showJob} />
        <RejectsReminder status={status} inRejectsView={browseView === "rejects" && !focus} />
        {actionError && <p className="error banner" role="alert">{actionError} <button onClick={() => setActionError(null)}>Dismiss</button></p>}
      </header>

      <main id="main-content" tabIndex={-1} className={`content ${datesOpen ? "dates-open" : ""}`} ref={content}>
        {!focus && (
          <>
            <aside className="side-panel" ref={side} style={sideWidth ? { flexBasis: `${sideWidth}px` } : undefined}>
              <TypesPanel types={typeCounts} selected={types} onTypes={changeTypes} />
              <BrowseBySwitch value={browseBy} onChange={setBrowseBy} />
              {browseBy === "folders"
                ? <FoldersPanel tree={folderTree} folders={folders} onFolders={changeFolders} />
                : <DatesPanel timeline={timeline} dates={dates} current={currentDates} oldestFirst={browseSort === "oldest"}
                              sortedByDate={browseSort === "newest" || browseSort === "oldest"}
                              onOrder={(oldest) => chooseSort(oldest ? "oldest" : "newest")} onDates={changeDates}
                              onJump={(key) => { jumpTo(key); setDatesOpen(false); }} />}
            </aside>
            <div className="divider side-divider" role="separator" aria-orientation="vertical" aria-label="Resize the left panel"
                 aria-valuemin={SIDE_MIN} aria-valuemax={SIDE_MAX} aria-valuenow={Math.round(currentSide())} aria-valuetext={`${Math.round(currentSide())} pixels wide`}
                 tabIndex={0} onPointerDown={dragSide}
                 onKeyDown={(e) => {
                   if (e.key === "ArrowLeft") { e.preventDefault(); setSideWidth(currentSide() - 40); }
                   if (e.key === "ArrowRight") { e.preventDefault(); setSideWidth(currentSide() + 40); }
                 }} />
          </>
        )}
        <div className="gallery-pane">
          {loadError && <p className="error">{loadError}</p>}
          {notice && (
            <p className="notice" role="status">
              {notice.text}
              {notice.actions.map((a) => <span key={a.label}> <button className="link" onClick={a.run}>{a.label}</button> ·</span>)}
              {" "}<button className="link" onClick={() => setNotice(null)}>Dismiss</button>
            </p>
          )}
          {focus && review && focus.mode && (
            <div className="focus-head review-bar" role="region" aria-label={`Review before ${REVIEW_WORDS[focus.mode].doing}`}>
              <div className="review-text">
                <strong>{focus.keep != null ? `Keeping ${focus.keepName}` : `Review before ${REVIEW_WORDS[focus.mode].doing}`}</strong>
                <span className="muted"> · {count(reviewIds.length)} of {plural(focus.ids.length, focus.keep != null ? "look-alike" : "selected photo")} will
                  be {REVIEW_WORDS[focus.mode].done}. Untick any you {focus.keep != null ? "want to keep" : "don't want"}.</span>
                {focus.leftOut ? <p className="muted">{plural(focus.leftOut, "selected photo is", "selected photos are")} left out: {TAKES[focus.mode]}.</p> : null}
                <p className="muted">{review.body[0]}</p>
              </div>
              <button className={review.danger ? "danger" : "primary"} onClick={commit}
                      disabled={committing || jobRunning || reviewIds.length === 0}
                      title={reviewIds.length === 0 ? "Every photo is unticked." : jobRunning ? "A job is running." : undefined}>
                {REVIEW_WORDS[focus.mode].button} {plural(reviewIds.length, "photo")}
              </button>
              <button onClick={backToResults} disabled={committing}>Cancel</button>
            </div>
          )}
          {focus && !review && (
            <div className="focus-head">
              <strong>
                {focus.kind === "set" ? `Photos in this reference set at ${focus.threshold}% or higher`
                  : focus.kind === "photo" ? "Showing the inspected photo"
                  : `Showing only the ${plural(focus.ids.length, "selected photo")}`}
              </strong>
              <span className="muted">
                {focus.kind === "set" ? "Selection is unchanged; all direct members are shown." : " · whatever the view, search or dates would hide."}
              </span>
              <button onClick={backToResults}>Back to results</button>
              {focusData && focusData.missing.length > 0 && (
                <p className="warning">
                  {focus.kind === "photo" ? "This photo is no longer in the catalog." : <>
                    {plural(focusData.missing.length, "selected photo is", "selected photos are")} no longer in the catalog.{" "}
                    <button className="link" onClick={() => toggleIds(focusData.missing, false)}>Remove from the selection</button>
                  </>}
                </p>
              )}
            </div>
          )}
          {!focus && jobRun != null && (
            <div className="focus-head" role="region" aria-label="A job's photos">
              <strong>{jobInfo ? `The ${data ? plural((data.counts as Record<string, number>).job ?? 0, "photo") : "photos"} in ${jobLabel(jobInfo.id, jobInfo.mode)}` : "A job's photos"}</strong>
              <span className="muted">
                {jobInfo && (["Preparing", "Running", "Cancelling"].includes(jobInfo.status) ? " · their status updates when the job ends."
                  : jobInfo.outcome ? ` · ${summary(jobInfo).detail}` : "")}
              </span>
              <button onClick={leaveJob}>Back to results</button>
            </div>
          )}
          {!focus && browseView === "rejects" && data?.rejects && <RejectsLine rejects={data.rejects} />}
          {!focus && <div className="gallery-context">
            <h2>{VIEW_LABEL[view]}</h2>
            {(undated || dates.length > 0 || types.length > 0 || folders.length > 0 || !!q || similar || suspicious) && <p className="section-note">
              {[similar && "Has similar photos", suspicious && "Suspicious dates", undated && "No capture date", q && `Filenames matching “${q}”`, ...dates.map(dateLabel), ...types.map(typeLabel), ...folders.map(folderLabel)].filter(Boolean).join(" · ")}
              {" "}<button className="link" onClick={() => { setSimilar(false); setSuspicious(false); setUndated(false); setReason("all"); if (sort === "matches") setSort("newest"); setQ(""); setSearch(""); setDates([]); setTypes([]); setFolders([]); setPage(1); }}>Clear filters</button>
            </p>}
          </div>}
          {!focus && view === "unorganized" && data?.index_summary && data.index_summary.photos > 0 && (indexSummaryClosed
            ? <button ref={summaryToggle} onClick={() => { setPreviewSummaryExpanded(true); toggleIndexSummary(null); }}>Show index summary</button>
            : <section className="notice index-summary" aria-label="Index summary">
            <div className="index-summary-heading"><h3>{indexNeedsAttention ? `${plural(data.index_summary.failed, "file")} ${data.index_summary.failed === 1 ? "needs" : "need"} attention` : "Index summary"}</h3>
              <button ref={summaryToggle} className="icon" aria-label="Close index summary" title="Close index summary"
                onClick={() => toggleIndexSummary(indexSummaryKey)}>✕</button>
            </div>
            <p>{indexNeedsAttention ? "The remaining files have processing errors. Review the failures to see what needs fixing." : "Your photos are indexed. Copy or move them to build your library."}</p>
            <p className="section-note">Photo facts below cover successfully indexed photos, before gallery filters. Failed files are counted separately. Size and date findings do not prevent Copy or Move.</p>
            <dl>
              <div><dt>Photos ready to organize</dt><dd>{count(data.index_summary.ready)}</dd></div>
              <div><dt>Additional identical copies</dt><dd>{count(data.index_summary.duplicates)}</dd></div>
              <div><dt>Small images</dt><dd>{data.index_summary.minimum == null ? "Rule disabled" : `${count(data.index_summary.small)} below ${count(data.index_summary.minimum)} pixels on the shorter side`}</dd></div>
              <div><dt>Suspicious dates</dt><dd>{count(data.index_summary.suspicious)}</dd></div>
              <div><dt>No capture date</dt><dd>{count(data.index_summary.undated)}</dd></div>
              <div><dt><Tip text="No usable width and height were recorded. The format may be unsupported, the file may be unreadable, or processing may be incomplete. This alone does not mean the file is damaged or is not a photo. These files are not counted as small images.">Image size unavailable</Tip></dt><dd>{count(data.index_summary.unknown_dimensions)}</dd></div>
              <div><dt>Files needing attention</dt><dd>{count(data.index_summary.failed)}</dd></div>
              {data.index_summary.unfinished > 0 && <div><dt>Unfinished processing</dt><dd>{count(data.index_summary.unfinished)}</dd></div>}
            </dl>
            <p className="section-note">Similar photos compares organized photos in Library only. Identical content is organized once. Files with processing errors: {count(data.index_summary.failed)}. <a href={data.index_summary.failed > 0 ? "/logs?status=Failed" : "/logs"} onClick={follow}>{data.index_summary.failed > 0 ? "View failures" : "View job details"}</a></p>
            {!indexNeedsAttention && <><button className="primary" disabled={jobRunning || !status.eligible.copy} title={jobRunning ? "Wait for the current job to finish." : !status.eligible.copy ? "No photos are eligible for Copy." : undefined} onClick={() => askTransfer("copy")}>Copy all photos…</button>{" "}
            <button disabled={jobRunning || !status.eligible.move} title={jobRunning ? "Wait for the current job to finish." : !status.eligible.move ? "No photos are eligible for Move." : undefined} onClick={() => askTransfer("move")}>Move all photos…</button></>}
          </section>)}
          {!focus && view === "review" && <>
            {reviewReturn && <button onClick={backToLibrary}>← Back to Library</button>}
            <p className="notice">Organized photos in Library awaiting a decision. These photos also appear in Library; the counts do not add together.</p>
            <div className="photo-actions"><button disabled={!data?.total} title={!data?.total ? "No photos match these review filters." : undefined}
              onClick={() => setReviewPhoto(data!.items[0].id)}>Review one by one</button></div>
            <StableContent active={reason} variants={{
              all: <p className="section-note">Use the filters above to focus your review. Click an active filter again to clear it.</p>,
              small: <p className="section-note">Small size is a reason to look, not a reason to reject. Mark reviewed clears a photo’s size reminder. <button className="photo-action" onClick={() => window.dispatchEvent(new Event("ns-review-settings"))}>Change in Settings</button></p>,
              later: <p className="section-note">Photos you marked to revisit. Done clears the reminder and leaves the photo in place.</p>,
            }} />
          </>}
          <div className="gallery-summary">
            <span>{gallerySummary ? plural(gallerySummary.total, galleryNoun) : "Loading photos…"}</span>
            {!focus && <div className="gallery-filter-summary">
              {data && (dates.length > 0 || types.length > 0 || folders.length > 0 || !!q || undated) && (
                <span className="gallery-filters">
                  {/* What is shown, against the library the view buttons count. */}
                  <Tip text={`Only ${[...folders.map(folderLabel), ...dates.map(dateLabel), ...types.map(typeLabel), ...(q ? [`filenames matching “${q}”`] : []), ...(undated ? ["photos without a capture date"] : [])].join(", ")}`}>
                    <span>{grouped ? `${count(data.total)} sets matching filters` : `Showing ${count(data.total)} of ${plural((data.counts as Record<string, number>)[browseView] ?? 0, galleryNoun)}`}</span>
                  </Tip>
                  {data && data.total > 0 && (
                    <> · <button className="link" onClick={selectAll} disabled={jobRunning}
                                 title={jobRunning ? "Selection is unavailable while a job is running." : undefined}>
                      Select these {count(data.total)}
                    </button></>
                  )}
                {dates.length > 0 && <>{" · "}<button className="link" onClick={() => changeDates([])}>Show all dates</button></>}
                {types.length > 0 && <>{" · "}<button className="link" onClick={() => changeTypes([])}>Show all types</button></>}
                {folders.length > 0 && <>{" · "}<button className="link" onClick={() => changeFolders([])}>Show all folders</button></>}
              </span>
            )}
            </div>}
            {similar && focus?.kind !== "set" && focus?.kind !== "review" && <span className="similar-summary-controls">
              {similarityPlace && <label title={groupingUnavailable ?? undefined}><input type="checkbox" checked={grouped} disabled={!!groupingUnavailable}
                aria-describedby={hasAdditionalFilters && !focus ? "gallery-guidance" : undefined}
                onChange={e => { setGroupSets(e.target.checked); setPage(1); savePreference("ns.groupSets", String(e.target.checked)); setExploreReference(null); }} />Group similar photos</label>}
              <label className="gallery-match-threshold">Matches at or above
                <select aria-label="Gallery match threshold" value={matchMin} disabled={!!focus}
                        onChange={e => { chooseMatchMinimum(Number(e.target.value)); }}>
                  {MATCH_THRESHOLDS.map(t => <option key={t} value={t}>{t}%</option>)}
                </select>
              </label>
              <button className={sort === "matches" ? "active" : "primary"} aria-pressed={sort === "matches"}
                      onClick={() => { chooseSort("matches"); }}>Most matches first</button>
              <Tip text="Gallery totals count sets when grouping is on; sidebar and view counts count photos. Match counts include direct matches across the destination library, including outside these filters. Open a photo to review its matches. Percentages measure visual similarity, not confidence; 100% does not mean identical files.">
                <span className="muted">{matchMin < 90 ? "Below 90%, matches are more likely to be unrelated." : "Counts cover the destination library."}</span>
              </Tip>
            </span>}
          </div>
          {!focus && similar && data?.similarity && (data.similarity.pending > 0 || data.similarity.unavailable > 0) && <p className="dates-filter-line">
            Counts may be incomplete: {plural(data.similarity.pending, "photo awaiting comparison", "photos awaiting comparison")};
            {" "}{plural(data.similarity.unavailable, "photo without a usable visual hash", "photos without a usable visual hash")}.
          </p>}
          {!focus && <StableContent id="gallery-guidance" className="gallery-guidance" active={suspicious ? (similar && hasAdditionalFilters ? "filtered-dates" : "dates")
           : grouped ? "groups" : similar && hasAdditionalFilters ? "filtered" : "browse"} variants={{
           browse: <p className="section-note">Filters narrow the gallery. Checkboxes select photos for actions.</p>,
           dates: <p className="section-note">Date review: before {data?.date_min_year ?? "your earliest expected year"} or more than one year ahead. Dates are unchanged. <button className="link" onClick={() => window.dispatchEvent(new Event("ns-review-settings"))}>Change in Settings</button></p>,
           groups: <p className="section-note">Identical sets appear once; partially overlapping sets remain separate. Set members come from the full destination library. Checkboxes select only the reference photo. Turn grouping off to see every photo.</p>,
           filtered: <p className="section-note">Showing every photo that matches all active filters. Clear the other filters to group similar photos.</p>,
           "filtered-dates": <p className="section-note">Showing every photo that matches all active filters. Clear the other filters to group similar photos. Date review: before {data?.date_min_year ?? "your earliest expected year"} or more than one year ahead. Dates are unchanged. <button className="link" onClick={() => window.dispatchEvent(new Event("ns-review-settings"))}>Change in Settings</button></p>,
         }} />}
          <SimilarityRecovery visible={!focus && similar && !!data?.similarity && (data.similarity.pending > 0 || data.similarity.unavailable > 0)} />
          {!focus && similar && data?.counts.organized === 0 && <p className="dates-filter-line">
            Copy or Move indexed photos to the destination first.
          </p>}
          {!focus && data && data.total === 0 && (
            <div className="empty">
              {noPhotos ? (
                <>
                  <h2>{view === "unorganized" ? "Index your source to find photos" : view === "organized" ? "No photos organized yet" : view === "review" ? "Nothing needs review yet" : "No rejected photos"}</h2>
                  {view === "unorganized" ? <><p>Indexing reads your source photos; nothing is moved or copied.</p><button className="primary" onClick={start("index")} disabled={jobRunning} aria-live="polite">{submission.pending?.body.mode === "index" ? "Starting…" : "Index source"}</button></>
                    : <button onClick={() => chooseView("unorganized")}>Go to Not organized</button>}
                </>
              ) : q ? (
                <>
                  <p>No {VIEW_LABEL[view].toLowerCase()} match “{q}”.</p>
                  {PLACE_VIEWS.filter((v) => v !== view && v !== "review" && (data.elsewhere?.[v] ?? 0) > 0).map((v) => (
                    <button key={v} onClick={() => { setSimilar(false); setSuspicious(false); setUndated(false); setDates([]); setTypes([]); setFolders([]); setReason("all"); chooseView(v); }}>{count(data.elsewhere?.[v] ?? 0)} matches in {VIEW_LABEL[v]}</button>
                  ))}
                </>
              ) : view === "organized" && data.counts.organized === 0 ? <><h2>No photos organized yet</h2><p>Copy or move your indexed photos into Library.</p><button onClick={() => chooseView("unorganized")}>Go to Not organized</button></> : view === "unorganized" && data.counts.unorganized === 0 ? <><h2>No photos waiting to be organized</h2>{data.counts.organized > 0 && <><p>Your organized photos are in Library.</p><button className="primary" onClick={() => chooseView("organized")}>Go to Library</button></>}</> : <p>Nothing in this view.</p>}
            </div>
          )}
          {list.meta && list.meta.total > 0 && (
            <>
              <div className="gallery-head">
                <SelectMenu onScreen={screenItems.length} screenSelected={screenSelected}
                            total={list.meta.total} selected={selected.size}
                            disabledWhy={jobRunning ? "Selection is unavailable while a job is running." : null}
                            onSelectScreen={() => toggleMany(screenItems, true)} onSelectAll={selectAll}
                            onUnselectScreen={() => toggleMany(screenItems, false)} onUnselectAll={clearSelection} />
                {jobRunning && <span className="muted">Selection is unavailable while a job is running.</span>}
              </div>
              <Pager noun={galleryNoun} page={visible} pages={pages} total={list.meta.total} pageSize={pageSize} onPage={onPager} onPageSize={changePageSize} continuous />
              {list.refreshError && <div className="notice" role="status">Updates could not be loaded. {list.refreshError}
                <button onClick={list.retryRefresh}>Retry updates</button></div>}
              {list.first > 1 && <PageBoundary ref={topSentinel} previous pending={list.pending.has(list.first - 1)} error={list.failures.get(list.first - 1)}
                onLoad={() => { prepend.current = { height: document.documentElement.scrollHeight, y: window.scrollY }; list.load(list.first - 1, true); }} />}
              <Gallery onNeedsReview={view === "organized" && !focus ? openNeedsReview : undefined} onReview={view === "review" && !focus ? setReviewPhoto : undefined} refreshKey={refreshKey} page={{ items: flat.items }} pageOf={flat.pageOf} selected={selected} place={place} selectable={!jobRunning} openId={openId}
                       keepItem={keepId != null ? keptItem : null}
                       onOpen={openFromGallery} onToggle={toggle} onToggleMany={toggleMany}
                       onReviewSet={grouped ? id => reviewSet(id, null) : undefined}
                       onExploreSet={grouped ? setExploreReference : undefined}
                       matchThreshold={focus?.kind === "set" ? focus.threshold : focus?.kind === "review" ? undefined : focus ? galleryMinimum : data?.similarity?.threshold} />
              {list.last < pages
                ? <PageBoundary ref={bottomSentinel} pending={list.pending.has(list.last + 1)} error={list.failures.get(list.last + 1)} onLoad={() => list.load(list.last + 1, true)} />
                : <div className="gallery-foot">
                    <span className="muted">End of {plural(list.meta.total, galleryNoun)}.</span>
                  </div>}
            </>
          )}
        </div>
        {openId != null && (
          <>
            <div className="divider" role="separator" aria-orientation="vertical" aria-label="Resize the photo panel"
                 aria-valuemin={MIN_SIDE} aria-valuemax={inspectorMax}
                 aria-valuenow={Math.round(currentWidth())} aria-valuetext={`${Math.round(currentWidth())} pixels wide`}
                 tabIndex={0} onPointerDown={drag}
                 onKeyDown={(e) => {
                   if (e.key === "ArrowLeft") { e.preventDefault(); e.stopPropagation(); setWidth(currentWidth() + 40); }
                   if (e.key === "ArrowRight") { e.preventDefault(); e.stopPropagation(); setWidth(currentWidth() - 40); }
                 }} />
            <Inspector onReviewPhoto={() => setReviewPhoto(openId!)} setBrowse={setBrowse} onOpenSet={reviewSet} onShowSet={showSet} coveredByDialog={exploreReference != null && similar && !focus} key={`${openId}:${comparisonNavigation}`} comparison={comparison?.origin === openId ? comparison : null} onComparison={setComparison} refreshKey={refreshKey} id={openId} width={effectivePanelWidth} onClose={() => { setOpenId(null); setLocate(null); setRevealId(null); }} onStep={step}
                       onOpenPhoto={openAndLocate} jobRunning={jobRunning} matchView={matchView} tab={inspectorTab}
                       onReject={(name) => askTransfer("reject", [openId], undefined, name)} onReturn={() => askTransfer("return", [openId])}
                       onRejectMatch={(id, name) => askTransfer("reject", [id], undefined, name)} onKeep={(keep, name, threshold) => void keepAndReview(keep, name, threshold)}
                       onNotice={(text, actions, photo) => setNotice(text,
                         actions.map((a) => ({ ...a, run: () => { setNotice(null); a.run(); } })), photo)}
                       onTab={(tab) => { setInspectorTab(tab);
                         if (tab === "similar" && !matchView) setMatchState({ photo: openId, view: { threshold: similar ? matchMin : 90, page: 1 } }); }}
                       onMatchView={(v) => setMatchState({ photo: openId, view: v })} />
          </>
        )}
      </main>

      {exploreReference != null && similar && !focus && <ReferenceSets key={exploreReference}
        reference={exploreReference} threshold={matchMin} refreshKey={refreshKey} suspended={comparison != null}
        onShowSet={showSet} onThreshold={chooseMatchMinimum} onClose={() => setExploreReference(null)} onReview={reviewSet} />}
      {reviewPhoto != null && <ReviewWorkspace initialPhoto={reviewPhoto} filters={{ view: browseView, q, undated, dates, types, folders, similar, suspicious, reason: reviewFilter, match_min: matchMin }} sort={browseSort} status={status}
        onBack={() => { setReviewPhoto(null); setRefreshKey(n => n + 1); }} onPhoto={setReviewPhoto} />}
      {confirm && <ConfirmDialog confirm={confirm} onClose={() => setConfirm(null)} />}
    </div>
  );
}
