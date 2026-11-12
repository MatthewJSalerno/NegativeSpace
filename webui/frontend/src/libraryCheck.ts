import type { LibraryCheck } from "./api";
import { count } from "./format";

// How a Check library result reads (webui-spec 7.6), shared by the sidebar status, the
// Check library dialog and the check's Logs entry. The words always state the count, so
// the box's colour is never the only signal.
export function checkResult(check: LibraryCheck): string {
  const lost = [check.lost && `${count(check.lost)} missing`, check.damaged && `${count(check.damaged)} damaged`].filter(Boolean);
  const parts = [lost.join(", "), check.attention && `${count(check.attention)} ${check.attention === 1 ? "needs" : "need"} attention`]
    .filter(Boolean);
  return parts.join(" · ") || "all as recorded";
}

export function depthName(depth: LibraryCheck["depth"]): string {
  return depth === "full" ? "Thorough" : "Quick";
}

export const ACTIVE = ["Preparing", "Running", "Cancelling"];

// Why a check could not run, in the words the engine's guard uses.
export function stoppedReason(check: LibraryCheck): string {
  return check.stopped === "library_missing" ? "The library folder isn't there. Is the destination connected?"
    : "It stopped before checking. See its log.";
}

// The Notice tone for a result: plain text when all is as recorded.
export function noticeClass(tone: LibraryCheck["tone"] | "quiet"): string {
  return tone === "bad" ? "notice notice-bad" : tone === "warn" ? "notice notice-warn" : "";
}

// Fired when a check starts, so the sidebar status updates at once.
export const CHECK_STARTED = "ns-library-check-started";

// What each kind of finding is called in the check's Logs entry.
export const FINDING_LABEL: Record<string, string> = {
  moved: "Moved", missing: "Missing", replaced: "Replaced", changed: "Changed", unreadable: "Unreadable",
  extra_copy: "Extra copy", moved_here: "Moved here", unknown_photo: "Not catalogued", wrong_extension: "Wrong name",
  other_type: "Other type", unrecognised: "Unknown kind", empty: "Empty", damaged: "Damaged", unopenable: "Can't open",
  unreadable_name: "Unreadable name",
};

// Other programs' housekeeping, by program (engine/library_check.py).
export const HOUSEKEEPING_LABEL: Record<string, string> = {
  synology: "Synology thumbnails and recycle bin", macos: "Mac system files", windows: "Windows system files",
  picasa: "Picasa settings", trash: "Linux trash", hidden: "hidden files",
};
