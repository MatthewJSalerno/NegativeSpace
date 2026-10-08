import { useSyncExternalStore } from "react";

export type Palette = "cool" | "warm";
export type Theme = "system" | "light" | "dark";
const listeners = new Set<() => void>();
let palette: Palette = "cool";
let theme: Theme = "system";
let dark = false;
const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
function stored(key: string) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function apply() {
  dark = theme === "dark" || (theme === "system" && systemDark.matches);
  document.documentElement.dataset.palette = palette;
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  listeners.forEach(notify => notify());
}
function read() {
  palette = stored("ns.palette") === "warm" ? "warm" : "cool";
  const value = stored("ns.theme");
  theme = value === "dark" || value === "light" ? value : "system";
  apply();
}
// Apply before React mounts; browser preferences are independent of the catalog.
export function initializeAppearance() {
  read();
  systemDark.addEventListener("change", apply);
  window.addEventListener("storage", event => {
    if (event.key === "ns.palette" || event.key === "ns.theme" || event.key === null) read();
  });
}
export function setPalette(next: Palette) {
  try { localStorage.setItem("ns.palette", next); } catch { /* Works for this page. */ }
  palette = next; apply();
}
export function setTheme(next: Theme) {
  try { localStorage.setItem("ns.theme", next); } catch { /* Works for this page. */ }
  theme = next; apply();
}
function subscribe(notify: () => void) {
  listeners.add(notify);
  return () => { listeners.delete(notify); };
}
export function usePalette() { return useSyncExternalStore(subscribe, () => palette); }
export function useTheme() { return useSyncExternalStore(subscribe, () => theme); }
export function useDarkMode() { return useSyncExternalStore(subscribe, () => dark); }
