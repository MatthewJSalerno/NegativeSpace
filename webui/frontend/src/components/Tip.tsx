import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";

// Supplemental help is available by hover, keyboard focus, or an explicit touch
// button. Keep essential instructions in the page. Escape dismisses only this help.
// `content` replaces the plain text with richer help, such as a diagram; `wide` gives
// it room. `text` stays the help's plain-text form.
export function Tip({ text, content, wide = false, showIcon = true, children }: { text: string; content?: ReactNode; wide?: boolean; showIcon?: boolean; children: ReactNode }) {
  const id = useId();
  const root = useRef<HTMLSpanElement>(null);
  const bubble = useRef<HTMLSpanElement>(null);
  const leaveTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(leaveTimer.current), []);
  const [open, setOpen] = useState(false);
  useLayoutEffect(() => {
    // The native top layer escapes sticky panels and overflow clipping, including
    // when this help belongs to a modal dialog. Keep it in the DOM for hover/focus.
    if (!open || !bubble.current) return;
    bubble.current.showPopover();
    const place = () => {
      // Passive label help sits outside the enclosing row, including adjacent controls.
      const anchor = (showIcon ? root.current : root.current?.parentElement)?.getBoundingClientRect();
      const help = bubble.current?.getBoundingClientRect();
      if (!anchor || !help) return;
      const next = {
        left: Math.max(16, Math.min(!showIcon ? anchor.right + 8 : anchor.left, window.innerWidth - help.width - 16)),
        top: Math.max(16, Math.min(!showIcon && anchor.right + help.width + 24 <= window.innerWidth ? anchor.top : anchor.bottom + 2, window.innerHeight - help.height - 16)),
      };
      setPosition(previous => previous.left === next.left && previous.top === next.top ? previous : next);
    };
    place();
    const observer = new ResizeObserver(place);
    observer.observe(bubble.current);
    if (root.current) observer.observe(root.current);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, wide, showIcon]);
  const [pinned, setPinned] = useState(false);
  const [position, setPosition] = useState({ left: 16, top: 16 });
  const show = () => {
    window.clearTimeout(leaveTimer.current);
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
    {showIcon && <button type="button" className="help-trigger" aria-label="More information" aria-expanded={open}
      aria-controls={open ? id : undefined} aria-describedby={open ? id : undefined}
      onClick={() => { if (pinned) { setPinned(false); setOpen(false); } else { setPinned(true); show(); } }}>ⓘ</button>}
    {open && <span ref={bubble} popover="manual" id={id} className={`help-content${wide ? " help-wide" : ""}${!showIcon ? " help-passive" : ""}`} role="note" tabIndex={showIcon ? 0 : undefined} style={position}>{content ?? text}</span>}
  </span>;
}
