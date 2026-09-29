import { useEffect } from "react";
import { MATCH_THRESHOLDS } from "../api";

// Old bookmarks land in the gallery. A reference bookmark opens its Inspector
// matches; old queue page/sort parameters do not describe gallery pages.
export function SimilarRedirect() {
  useEffect(() => {
    const old = new URLSearchParams(location.search);
    const params = new URLSearchParams({ view: "similar" });
    if (old.get("q")) params.set("q", old.get("q")!);
    if (Number(old.get("photo")) > 0) {
      params.set("photo", old.get("photo")!);
      const threshold = Number(old.get("threshold"));
      params.set("match", String(MATCH_THRESHOLDS.includes(threshold) ? threshold : 90));
      const page = Number(old.get("match_page"));
      if (Number.isSafeInteger(page) && page > 1) params.set("match_page", String(page));
    }
    history.replaceState(null, "", `/?${params}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, []);
  return <p role="status">Opening gallery…</p>;
}
