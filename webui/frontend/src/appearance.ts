import { useSyncExternalStore } from "react";

export type Palette = "cool" | "warm";
const KEY = "ns.palette";
const listeners = new Set<() => void>();
let palette: Palette = "cool";

function read(): Palette {
  try { return localStorage.getItem(KEY) === "warm" ? "warm" : "cool"; }
  catch { return "cool"; }
}

function apply(next: Palette) {
  palette = next;
  document.documentElement.dataset.palette = next;
  listeners.forEach((notify) => notify());
}

// Apply before mounting React to avoid flashing the default palette on reload.
export function initializeAppearance() {
  apply(read());
  window.addEventListener("storage", (event) => {
    if (event.key === KEY || event.key === null) apply(read());
  });
}

export function setPalette(next: Palette) {
  try { localStorage.setItem(KEY, next); } catch { /* Keep the choice for this page. */ }
  apply(next);
}

export function usePalette() {
  return useSyncExternalStore((notify) => {
    listeners.add(notify);
    return () => { listeners.delete(notify); };
  }, () => palette);
}
