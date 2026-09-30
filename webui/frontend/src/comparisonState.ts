import { MATCH_THRESHOLDS } from "./api";
import type { PreviewView } from "./components/ReviewPreview";

export type ComparisonState = {
  origin: number; reference: number; candidate: number | null; threshold: number; page: number;
  filter: "all" | "reviewed" | "unreviewed"; tab: "information" | "review";
  views: Record<number, PreviewView>; linked: boolean; share: number;
};
const id = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0;
export function readComparison(params: URLSearchParams): ComparisonState | null {
  const raw = params.get("review");
  if (!raw || raw.length > 2048) return null;
  try {
    const s = JSON.parse(raw);
    if (!s || !id(s.origin) || s.origin !== Number(params.get("photo")) || !id(s.reference)
      || (s.candidate !== null && (!id(s.candidate) || s.candidate === s.reference))
      || !MATCH_THRESHOLDS.includes(s.threshold) || !id(s.page) || s.page > 1000000
      || !["all", "reviewed", "unreviewed"].includes(s.filter) || !["information", "review"].includes(s.tab)
      || typeof s.linked !== "boolean" || !Number.isFinite(s.share) || s.share < 50 || s.share > 82) return null;
    const views: Record<number, PreviewView> = {};
    for (const photo of [s.reference, s.candidate]) {
      if (photo == null) continue;
      const v = s.views?.[photo];
      if (v && [0, 90, 180, 270].includes(v.rotation) && Number.isFinite(v.zoom) && v.zoom >= 1 && v.zoom <= 4
        && Number.isFinite(v.x) && v.x >= 0 && v.x <= 100 && Number.isFinite(v.y) && v.y >= 0 && v.y <= 100)
        views[photo] = { rotation: v.rotation, zoom: v.zoom, x: v.x, y: v.y };
    }
    return { origin:s.origin, reference:s.reference, candidate:s.candidate, threshold:s.threshold,
      page:s.page, filter:s.filter, tab:s.tab, views, linked:s.linked, share:s.share };
  } catch { return null; }
}
