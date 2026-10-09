import { setTheme, useDarkMode } from "../appearance";

// The top bar's tools, the same on every page: Dark mode, then Settings.
export function PageTools({ onOpenSettings }: { onOpenSettings: () => void }) {
  const dark = useDarkMode();
  return <div className="toolbar-actions">
    <button className={dark ? "active-soft" : undefined} aria-pressed={dark} onClick={() => setTheme(dark ? "light" : "dark")}
      title="Switch light/dark mode. System preference is available in Settings.">Dark mode</button>
    <button className="icon" onClick={() => onOpenSettings()} aria-label="Settings" title="Settings">⚙</button>
  </div>;
}
