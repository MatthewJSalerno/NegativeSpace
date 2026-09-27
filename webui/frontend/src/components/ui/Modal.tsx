import { useLayoutEffect, useRef, type ReactNode } from "react";
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
      <div className={className} tabIndex={-1}>{children}</div>
    </dialog>, document.body);
}
