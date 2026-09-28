import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

const openDialogs = new Set<HTMLDialogElement>();
let previousOverflow = "";
const tabbable = 'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"], summary';

// Native top-layer modality makes everything behind the window inert, including
// other dialogs. Explicit wrapping and restoration keep the keyboard in the task.
export function Modal({ children, onClose, labelledBy, label, role = "dialog", className = "dialog", busy = false }: {
  children: ReactNode; onClose: () => void; labelledBy?: string; label?: string;
  role?: "dialog" | "alertdialog"; className?: string; busy?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [scrollCue, setScrollCue] = useState({ above: false, below: false, left: 0, top: 0, bottom: 0 });
  useLayoutEffect(() => {
    const content = contentRef.current!;
    let frame = 0;
    const measure = () => {
      const rect = content.getBoundingClientRect();
      const next = { above: content.scrollTop > 2,
        below: content.scrollHeight - content.clientHeight - content.scrollTop > 2,
        left: rect.left + rect.width / 2, top: rect.top + 8, bottom: rect.bottom - 8 };
      setScrollCue(old => Object.keys(next).every(key => old[key as keyof typeof next] === next[key as keyof typeof next]) ? old : next);
    };
    const schedule = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(measure); };
    const resize = new ResizeObserver(schedule);
    resize.observe(content);
    const mutation = new MutationObserver(schedule);
    mutation.observe(content, { childList: true, subtree: true, attributes: true, characterData: true });
    content.addEventListener("scroll", schedule, { passive: true });
    content.addEventListener("load", schedule, true);
    window.addEventListener("resize", schedule);
    schedule();
    return () => {
      cancelAnimationFrame(frame); resize.disconnect(); mutation.disconnect();
      content.removeEventListener("scroll", schedule);
      content.removeEventListener("load", schedule, true);
      window.removeEventListener("resize", schedule);
    };
  }, []);
  useLayoutEffect(() => {
    const dialog = ref.current!;
    const opener = document.activeElement as HTMLElement | null;
    if (!openDialogs.size) { previousOverflow = document.body.style.overflow; document.body.style.overflow = "hidden"; }
    openDialogs.add(dialog);
    dialog.showModal();
    (dialog.querySelector<HTMLElement>("[data-initial-focus]") ?? dialog.querySelector<HTMLElement>(tabbable) ?? dialog.firstElementChild as HTMLElement).focus();
    return () => {
      dialog.close();
      openDialogs.delete(dialog);
      if (!openDialogs.size) document.body.style.overflow = previousOverflow;
      const fallback = [...openDialogs].at(-1)?.querySelector<HTMLElement>(tabbable)
        ?? document.querySelector<HTMLElement>('[data-focus-home], .actions-menu > button');
      (opener?.isConnected && opener !== document.body ? opener : fallback)?.focus({ preventScroll: true });
    };
  }, []);
  return createPortal(
    <dialog ref={ref} className="modal-shell" role={role} aria-modal="true" aria-labelledby={labelledBy}
            aria-label={label} aria-busy={busy || undefined}
            onCancel={(e) => { e.preventDefault(); if (!busy) onClose(); }}
            onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose(); }}
            onKeyDown={(e) => {
              // Keep photo/navigation shortcuts behind any dialog inactive.
              e.stopPropagation();
              if (e.key === "Escape") { e.preventDefault(); if (!busy) onClose(); }
              if (e.key !== "Tab") return;
              const nodes = [...e.currentTarget.querySelectorAll<HTMLElement>(tabbable)]
                .filter((el) => el.tabIndex >= 0 && el.getClientRects().length > 0);
              const first = nodes[0], last = nodes.at(-1);
              if (!first) { e.preventDefault(); (e.currentTarget.firstElementChild as HTMLElement).focus(); }
              else if (e.shiftKey && (document.activeElement === first || document.activeElement === e.currentTarget.firstElementChild)) {
                e.preventDefault(); last?.focus();
              } else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
            }}>
      <div ref={contentRef} className={className} tabIndex={-1}>{children}</div>
      {scrollCue.above && <span className="modal-scroll-cue above" aria-hidden="true"
        style={{ left: scrollCue.left, top: scrollCue.top }}>↑ More above</span>}
      {scrollCue.below && <span className="modal-scroll-cue below" aria-hidden="true"
        style={{ left: scrollCue.left, top: scrollCue.bottom }}>More below ↓</span>}
    </dialog>, document.body);
}
