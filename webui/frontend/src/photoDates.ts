import type { PhotoDetail } from "./api";
import { isFallbackDate } from "./format";

const DATE_ISSUES = new Set(["invalid_date_taken", "invalid_date_fraction", "invalid_date_offset", "date_components_without_date"]);

export function blockingDateIssue(photo: PhotoDetail) {
  return photo.metadata_attention?.issues.find(issue => DATE_ISSUES.has(issue.code));
}

// Use the effective filing date, which may come from XMP rather than EXIF.
export function captureDateMessage(photo: PhotoDetail): string | null {
  if (photo.status === "Failed" || (photo.date_taken && !isFallbackDate(photo.date_source))) return null;
  if (blockingDateIssue(photo)) return null; // The source-attention notice explains this once.
  if (photo.exif_dates?.some(date => date.field === "taken")) return "The recorded Date taken is not usable for filing. Check the Metadata tab for its value and source.";
  return "No complete Date taken is available for filing. Check the Metadata tab for missing, empty or partial dates.";
}
