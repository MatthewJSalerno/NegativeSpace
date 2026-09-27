import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";

export interface MenuEntry { label: string; hint?: string; why?: string | null; onClick?: () => void; children?: MenuEntry[] }

// Disabled commands stay arrow-focusable so their explanation remains discoverable.
// Domain components provide commands; this component owns all menu interaction.
export function MenuButton({ label, items, className = "" }: { label: string; items: MenuEntry[]; className?: string }) {
  const [open, setOpen] = useState(false);
  const [last, setLast] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const id = useId();
  const close = (restore = true) => { setOpen(false); if (restore) trigger.current?.focus(); };
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);
  return <div ref={root} className={`actions-menu ${className}`}>
    <button ref={trigger} aria-haspopup="menu" aria-expanded={open} aria-controls={open ? id : undefined}
            className={open ? "active-soft" : ""} onClick={() => { setLast(false); setOpen(!open); }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                e.preventDefault(); e.stopPropagation(); setLast(e.key === "ArrowUp"); setOpen(true);
              }
            }}>{label} <span aria-hidden="true">▾</span></button>
    {open && <MenuList id={id} label={label} items={items} last={last} onExit={() => close()} onTab={() => close()}
                       onRun={(action) => { close(); action?.(); }} />}
  </div>;
}

function MenuList({ id, label, items, last = false, onExit, onTab, onRun, nested = false }: {
  id?: string; label: string; items: MenuEntry[]; last?: boolean; nested?: boolean;
  onExit: () => void; onTab: () => void; onRun: (action?: () => void) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [branch, setBranch] = useState<number | null>(null);
  const buttons = () => [...(ref.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [])]
    .filter((el) => el.closest('[role="menu"]') === ref.current);
  useLayoutEffect(() => { const all = buttons(); (last ? all.at(-1) : all[0])?.focus(); }, [last]);
  return <div ref={ref} id={id} className={`menu ${nested ? "submenu" : ""}`} role="menu" aria-label={label}
    onKeyDown={(e) => {
      e.stopPropagation();
      const all = buttons(), at = all.indexOf(document.activeElement as HTMLButtonElement);
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
        e.preventDefault();
        const next = e.key === "Home" ? 0 : e.key === "End" ? all.length - 1
          : (at + (e.key === "ArrowDown" ? 1 : -1) + all.length) % all.length;
        all[next]?.focus();
      } else if (e.key === "Escape" || (nested && e.key === "ArrowLeft")) { e.preventDefault(); onExit(); }
      else if (e.key === "Tab") onTab();
      else if (e.key === "ArrowRight" && items[at]?.children) { e.preventDefault(); setBranch(at); }
      else if (e.key.length === 1 && /\S/.test(e.key) && !e.ctrlKey && !e.metaKey) {
        const ordered = [...all.slice(at + 1), ...all.slice(0, at + 1)];
        ordered.find((el) => el.querySelector('.menu-label')?.textContent?.toLowerCase().startsWith(e.key.toLowerCase()))?.focus();
      }
    }}>
    {items.map((item, i) => <div className="menu-parent" role="none" key={item.label}>
      <button role="menuitem" tabIndex={-1} aria-disabled={!!item.why} aria-haspopup={item.children ? "menu" : undefined}
              aria-expanded={item.children ? branch === i : undefined}
              className={`menu-item ${item.children ? "menu-branch" : ""}`}
              onClick={() => { if (!item.why) { if (item.children) setBranch(branch === i ? null : i); else onRun(item.onClick); } }}>
        <span className="menu-label">{item.label}</span>
        {item.children && <span aria-hidden="true">▸</span>}
        {(item.why ?? item.hint) && <span className="menu-hint">{item.why ?? item.hint}</span>}
      </button>
      {item.children && branch === i && <MenuList nested label={item.label} items={item.children} onRun={onRun} onTab={onTab}
        onExit={() => { setBranch(null); buttons()[i]?.focus(); }} />}
    </div>)}
  </div>;
}
