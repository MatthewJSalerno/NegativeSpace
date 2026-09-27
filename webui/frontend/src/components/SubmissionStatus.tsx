import { useEffect, useSyncExternalStore } from "react";
import { checkSubmission, retrySubmission, submissionSnapshot, subscribeSubmission } from "../api";
import { follow, logUrl } from "../nav";

export function SubmissionStatus() {
  const state = useSyncExternalStore(subscribeSubmission, submissionSnapshot);
  useEffect(() => { if (state.pending && state.checking) void checkSubmission(); }, [state.pending?.id]);
  if (!state.pending && !state.resolved && !state.error) return null;
  return <aside className="notice submission-status" role="status" aria-label="Job submission status">
    {state.pending ? <>
      <strong>{state.checking ? "Checking job status…" : "Submitting job…"}</strong>
      <span> {state.checking ? "The response was not confirmed. This request may already have started." : "Waiting for this request to be accepted."}</span>
      {state.checking && <p><button onClick={() => void retrySubmission()}>Retry same request</button>{" "}
        <button onClick={() => void checkSubmission()}>Check again</button>{" "}
        <a href="/logs" onClick={follow}>View job history</a>.{" "}
        Retrying keeps the original scope and cannot start a second job for this request.</p>}
    </> : state.resolved ? <>
      Request accepted as job #{state.resolved.id}.{" "}
      <a href={logUrl({ run: state.resolved.id! })} onClick={follow}>View this job</a>
    </> : state.error}
  </aside>;
}
