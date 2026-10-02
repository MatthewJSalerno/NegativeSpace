import type { ReactNode } from "react";

// A row of tabs (WAI-ARIA Authoring Practices, "Tabs with automatic activation"): one tab
// stop, ← → to move and choose, Home and End for the ends. Each panel is
// `<div role="tabpanel" {...tabPanel(idBase, value)}>`.
export function TabList<T extends string>({ label, idBase, tabs, value, onChange, className }: {
  label: string;
  idBase: string;
  tabs: { value: T; label: ReactNode }[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div className={className} role="tablist" aria-label={label}>
      {tabs.map((tab, i) => (
        <button key={tab.value} role="tab" id={`${idBase}-${tab.value}`} aria-controls={`${idBase}-${tab.value}-panel`}
          aria-selected={value === tab.value} tabIndex={value === tab.value ? 0 : -1}
          onClick={() => onChange(tab.value)} onKeyDown={(e) => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
            e.preventDefault(); e.stopPropagation();
            const n = tabs.length;
            const next = e.key === "Home" ? 0 : e.key === "End" ? n - 1 : (i + (e.key === "ArrowRight" ? 1 : n - 1)) % n;
            onChange(tabs[next].value);
            document.getElementById(`${idBase}-${tabs[next].value}`)?.focus();
          }}>{tab.label}</button>
      ))}
    </div>
  );
}

export function tabPanel(idBase: string, value: string, selected: string) {
  return { id: `${idBase}-${value}-panel`, "aria-labelledby": `${idBase}-${value}`, hidden: value !== selected, tabIndex: 0 };
}
