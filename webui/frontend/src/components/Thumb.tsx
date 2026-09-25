import { useEffect, useState } from "react";
import { api } from "../api";

const REASONS: Record<string, string> = {
  file_unavailable: "Photo file unavailable",
  permission_denied: "Permission denied reading photo",
  decode_failed: "Image could not be decoded",
  cache_write_failed: "Thumbnail cache could not be written",
  decoder_unavailable: "No decoder for this format",
};

// A thumbnail, or a placeholder that says why there is none (webui-spec 4.2.1): a
// cache miss is "not made yet", not a failure; a recorded failure names its cause.
export function Thumb({ id, size = "grid", alt }: { id: number; size?: "grid" | "preview"; alt: string }) {
  const [failed, setFailed] = useState(false);
  const [reason, setReason] = useState<string | null>(null);

  useEffect(() => {
    setFailed(false);
    setReason(null);
  }, [id, size]);

  useEffect(() => {
    if (!failed) return;
    let live = true;
    api.thumbnailReason(id, size).then((r) => {
      if (!live || !r) return;
      if (r.availability === "pending") setReason("Preview not made yet");
      else setReason((r.failure_category && REASONS[r.failure_category]) || r.failure_detail || "Preview unavailable; reason not recorded.");
    });
    return () => {
      live = false;
    };
  }, [failed, id, size]);

  if (failed) {
    return (
      <div className="thumb-placeholder" title={reason ?? undefined}>
        <span>{reason ?? "…"}</span>
      </div>
    );
  }
  return <img src={api.thumbnailUrl(id, size)} alt={alt} loading="lazy" decoding="async" onError={() => setFailed(true)} />;
}
