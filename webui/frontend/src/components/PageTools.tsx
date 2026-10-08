import type { Status } from "../api";
import { setTheme, useDarkMode } from "../appearance";
import { VersionTag } from "./VersionTag";
import { follow } from "../nav";

// One ordering, labels and behavior across all top-level pages.
export function PageTools({ version, stats = false, onOpenSettings }: {
  version: Status["version"]; stats?: boolean; onOpenSettings: () => void;
}) {
  const dark = useDarkMode();
  return <div className="toolbar-actions">
    <VersionTag version={version} />
    <button className={dark ? "active-soft" : undefined} aria-pressed={dark} onClick={() => setTheme(dark ? "light" : "dark")}
      title="Switch light/dark mode. System preference is available in Settings.">Dark mode</button>
    <StatsLink active={stats} />
    <button className="icon" onClick={() => onOpenSettings()} aria-label="Settings" title="Settings">⚙</button>
  </div>;
}

function StatsLink({ active = false }: { active?: boolean }) {
  return (
    <a className={`icon stats-link ${active ? "active" : ""}`} href="/stats" onClick={follow}
       aria-label="Stats" title="Stats" aria-current={active ? "page" : undefined}>
      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"
           fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        <path d="M5 20V11M12 20V5M19 20v-7" />
      </svg>
    </a>
  );
}

