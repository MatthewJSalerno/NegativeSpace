// Rejecting and returning single photos from the similarity screens (webui-spec 7.8):
// the job runs like any other, and the screen waits for its result before moving on,
// one at a time (the engine runs one job at a time).
import { api, type Run } from "./api";

const ACTIVE = ["Preparing", "Running", "Cancelling"];

export async function runAndWait(mode: "reject" | "return", ids: number[]): Promise<Run> {
  const started = await api.startJob({ mode, file_ids: ids });
  let run = started;
  while (run.id != null && ACTIVE.includes(run.status)) {
    await new Promise((resolve) => setTimeout(resolve, 400));
    run = await api.run(run.id);
  }
  return run;
}

// How many of the job's photos it moved: Rejected for a reject, Returned for a return.
export function moved(run: Run, mode: "reject" | "return"): number {
  return run.outcome?.counts?.[mode === "reject" ? "Rejected" : "Returned"] ?? 0;
}
