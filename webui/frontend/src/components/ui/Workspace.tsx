import type { KeyboardEvent, ReactNode } from "react";
import { Modal } from "./Modal";

// Controls that use the arrow keys themselves; the workspace's ← → never override them.
const OWN_ARROWS = 'input, select, textarea, [contenteditable="true"], [role="tablist"], [role="tab"], [role="separator"], [role="slider"], [role="menu"], [role="menuitem"], [role="radiogroup"], [data-own-arrows]';

export interface WorkspaceStep {
  /** Where the user is, e.g. "Candidate 3 of 24". */
  position: string;
  /** Accessible names for the two buttons, e.g. "Previous candidate". */
  previousLabel: string;
  nextLabel: string;
  onPrevious: () => void;
  onNext: () => void;
  previousDisabled?: boolean;
  nextDisabled?: boolean;
}

// The full-window frame for deep work (ui-design.md "Workspaces"): a header with Back,
// the task and its subject, ‹ n of N › and the task's actions; the task's content; and a
// footer status line. It is a native modal over the Library, so the Library stays mounted
// and Back returns to exactly the filters, scroll position and selection the user left.
// Esc goes back and ← → step, stopping at the ends. (Leaving with unsaved changes will
// ask first; that guard arrives with the first workspace that edits, the EXIF editor.)
// `label` is the window's accessible name; the visible title may be longer.
export function Workspace({ label, title, subject, onBack, backLabel = "Back to gallery", step, actions,
                            status, busy = false, className = "", children }: {
  label: string;
  title: ReactNode;
  subject?: ReactNode;
  onBack: () => void;
  backLabel?: string;
  step?: WorkspaceStep;
  actions?: ReactNode;
  status?: ReactNode;
  busy?: boolean;
  className?: string;
  children: ReactNode;
}) {
  const requestBack = () => { if (!busy) onBack(); };
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!step || busy || e.defaultPrevented) return;
    if ((e.key !== "ArrowLeft" && e.key !== "ArrowRight") || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    if ((e.target as HTMLElement).closest(OWN_ARROWS)) return;
    e.preventDefault();
    if (e.key === "ArrowLeft" && !step.previousDisabled) step.onPrevious();
    if (e.key === "ArrowRight" && !step.nextDisabled) step.onNext();
  };
  return (
    <Modal label={label} className={`workspace ${className}`.trim()} onClose={requestBack} busy={busy}>
      <div className="workspace-frame" onKeyDown={onKeyDown}>
        <header className="workspace-header">
          <button className="workspace-back" disabled={busy} onClick={requestBack}>
            <span aria-hidden="true">← </span>{backLabel}
          </button>
          <div className="workspace-title">
            <h2>{title}</h2>
            {subject && <span className="workspace-subject">{subject}</span>}
          </div>
          {step && (
            <nav className="workspace-step" aria-label="Step through">
              <button aria-label={step.previousLabel} title={`${step.previousLabel} (←)`}
                      disabled={busy || step.previousDisabled} onClick={step.onPrevious}>‹</button>
              <span aria-live="polite">{step.position}</span>
              <button aria-label={step.nextLabel} title={`${step.nextLabel} (→)`}
                      disabled={busy || step.nextDisabled} onClick={step.onNext}>›</button>
            </nav>
          )}
          {actions && <div className="workspace-actions">{actions}</div>}
        </header>
        <div className="workspace-content">{children}</div>
        <footer className="workspace-status">
          <div className="workspace-status-text">{status}</div>
          <span className="workspace-keys">{step ? "← → step · " : ""}Esc returns to the gallery</span>
        </footer>
      </div>
    </Modal>
  );
}
