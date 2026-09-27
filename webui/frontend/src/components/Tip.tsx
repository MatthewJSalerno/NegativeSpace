import { useEffect, useId, useRef, useState, type ReactNode } from "react";

// Supplemental help is available by hover, keyboard focus, or an explicit touch
// button. Keep essential instructions in the page. Escape dismisses only this help.
export function Tip({ text, children }: { text: string; children: ReactNode }) {
  const id = useId();
  const root = useRef<HTMLSpanElement>(null);
  const leaveTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(leaveTimer.current), []);
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [position, setPosition] = useState({ left: 16, top: 16 });
  const show = () => {
    window.clearTimeout(leaveTimer.current);
    const rect = root.current?.getBoundingClientRect();
    if (rect) setPosition({ left: Math.max(16, Math.min(rect.left, window.innerWidth - 296)),
      top: Math.min(rect.bottom + 2, window.innerHeight - 160) });
    setOpen(true);
  };
  return <span ref={root} className="tip" data-tip={text}
    onMouseEnter={show} onMouseLeave={() => {
      // Allow the pointer to cross the small gap to the help bubble.
      leaveTimer.current = window.setTimeout(() => {
        if (!pinned && !root.current?.contains(document.activeElement)) setOpen(false);
      }, 150);
    }}
    onFocus={show} onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) { setOpen(false); setPinned(false); } }}
    onKeyDown={(e) => { if (e.key === "Escape" && open) { e.preventDefault(); e.stopPropagation(); setOpen(false); setPinned(false); } }}>
    {children}
    <button type="button" className="help-trigger" aria-label="More information" aria-expanded={open}
      aria-controls={open ? id : undefined} aria-describedby={open ? id : undefined}
      onClick={() => { if (pinned) { setPinned(false); setOpen(false); } else { setPinned(true); show(); } }}>ⓘ</button>
    {open && <span id={id} className="help-content" role="note" style={position}>{text}</span>}
  </span>;
}
