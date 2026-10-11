import { setTheme, useDarkMode } from "../appearance";

// The top bar's tools, the same on every page: the Dark mode switch, then Settings. A
// switch (WAI-ARIA Switch pattern) shows on or off at a glance; System stays in Settings,
// and while it applies the switch shows the mode in effect.
export function PageTools({ onOpenSettings }: { onOpenSettings: () => void }) {
  const dark = useDarkMode();
  return <div className="toolbar-actions">
    <button type="button" role="switch" aria-checked={dark} className="theme-switch" onClick={() => setTheme(dark ? "light" : "dark")}
      title="Switch light/dark mode. System preference is available in Settings.">
      <span>Dark mode</span>
      <span className="theme-switch-track" aria-hidden="true"><span className="theme-switch-knob" /></span>
    </button>
    <button className="icon" onClick={() => onOpenSettings()} aria-label="Settings" title="Settings">⚙</button>
  </div>;
}
