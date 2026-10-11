import { useEffect, useState } from "react";
import type { LookInto } from "./api";

export const LOOK_KEYS: LookInto[] = ["similar", "suspicious", "undated", "small", "later", "issues"];
export const REASON_KEYS: LookInto[] = ["small", "later", "issues"];
const STORAGE_KEY = "ns.filterPins";
let fallback: LookInto[] = [];

export function savedFilterPins(): LookInto[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
    if (!Array.isArray(value)) return [];
    const reason = REASON_KEYS.find(key => value.includes(key));
    return LOOK_KEYS.filter(key => value.includes(key) && (!REASON_KEYS.includes(key) || key === reason));
  } catch { return fallback; }
}

export function filterApplies(key: LookInto, view: string): boolean {
  if (key === "issues") return view === "review";
  if (key === "later" || key === "similar" || key === "small") return view === "organized" || view === "review";
  return true;
}

// Pins are browser preferences. URLs still describe the actual filters: saved pins
// never silently narrow an explicit photo/job link or browser history entry.
export function useFilterPins() {
  const [pins, setPins] = useState(savedFilterPins);
  useEffect(() => {
    const changed = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY || event.key === null) setPins(savedFilterPins());
    };
    window.addEventListener("storage", changed);
    return () => window.removeEventListener("storage", changed);
  }, []);
  const save = (next: LookInto[]) => {
    fallback = next;
    setPins(next);
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch { /* Works for this visit. */ }
  };
  return { pins, save };
}
