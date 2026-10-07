import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { MatchPhoto } from "../api";
import { bytes } from "../format";
import { Thumb } from "./Thumb";

export type PreviewView = { rotation: number; zoom: number; x: number; y: number };
export const DEFAULT_VIEW: PreviewView = { rotation: 0, zoom: 1, x: 50, y: 50 };

export function ReviewPreview({ photo, label, view, onChange, refreshKey, isReference = false, onUseAsReference, referenceDisabled, action, prominent = false }: {
  photo: MatchPhoto; label: string; view: PreviewView; onChange: (next: PreviewView) => void; refreshKey: number; isReference?: boolean;
  onUseAsReference?: () => void; referenceDisabled?: boolean;
  // The photo's own action beside its name (Reject…), so it is clear which photo it acts on.
  action?: ReactNode; prominent?: boolean;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 1, height: 1 });
  useLayoutEffect(() => {
    const element = viewport.current!;
    const observer = new ResizeObserver(() => setSize({ width: element.clientWidth, height: element.clientHeight }));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const sideways = view.rotation % 180 !== 0;
  return <figure className="review-photo" data-reference={isReference} data-prominent={prominent} tabIndex={isReference ? -1 : undefined} aria-label={`${label} preview`}>
    <figcaption><div className="review-photo-heading">
      <strong className="review-photo-role">{isReference ? "Reference photo" : label}</strong>
      {onUseAsReference && <button className="photo-action" disabled={referenceDisabled} onClick={onUseAsReference}
        title="Find matches for this photo. This does not choose a keeper or metadata donor.">Use as reference</button>}
    </div><div className="review-photo-name"><span title={photo.filename}>{photo.filename}</span>{action}</div></figcaption>
    <div ref={viewport} className="review-viewport">
      <div className="review-zoom" style={{ transform: `scale(${view.zoom})`, transformOrigin: `${view.x}% ${view.y}%` }}>
        <div className="review-rotation" style={{ width: sideways ? size.height : size.width,
          height: sideways ? size.width : size.height, transform: `translate(-50%, -50%) rotate(${view.rotation}deg)` }}>
          <Thumb id={photo.id} size="preview" alt={`${label}: ${photo.filename}`} refreshKey={refreshKey} />
        </div>
      </div>
    </div>
    <div className="review-preview-controls">
      <div className="review-rotation-controls">
        <button aria-label={`Rotate ${label.toLowerCase()} left`} onClick={() => onChange({ ...view, rotation: (view.rotation + 270) % 360 })}>↶ Left</button>
        <button aria-label={`Rotate ${label.toLowerCase()} right`} onClick={() => onChange({ ...view, rotation: (view.rotation + 90) % 360 })}>↷ Right</button>
        <button onClick={() => onChange(DEFAULT_VIEW)} aria-label={`Reset ${label.toLowerCase()} view`}>Reset view</button>
      </div>
      <label>Zoom: {view.zoom}×<input aria-label={`Zoom ${label.toLowerCase()}`} type="range" min="1" max="4" step="0.25"
        value={view.zoom} onChange={(e) => onChange({ ...view, zoom: Number(e.target.value) })} /></label>
      {view.zoom > 1 && <div className="review-pan-controls">
        <label>Horizontal<input aria-label={`${label} horizontal position`} type="range" min="0" max="100" value={view.x}
          onChange={(e) => onChange({ ...view, x: Number(e.target.value) })} /></label>
        <label>Vertical<input aria-label={`${label} vertical position`} type="range" min="0" max="100" value={view.y}
          onChange={(e) => onChange({ ...view, y: Number(e.target.value) })} /></label>
      </div>}
      <p className="section-note">{photo.width && photo.height
        ? `${view.rotation !== 0 ? "Displayed: " : ""}${sideways ? photo.height : photo.width} × ${sideways ? photo.width : photo.height}`
        : "Dimensions unknown"} · {bytes(photo.file_size)}
        {view.rotation !== 0 && <span className="review-rotation-note">Viewing rotation: {view.rotation}° · not saved to file</span>}</p>
    </div>
  </figure>;
}
