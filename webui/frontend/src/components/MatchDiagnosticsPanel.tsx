import { useEffect, useState } from "react";
import { api, type MatchDiagnostics } from "../api";
import { count } from "../format";

export function MatchDiagnosticsPanel({ refreshKey, queueMs }: { refreshKey: string; queueMs?: number }) {
  const [data, setData] = useState<MatchDiagnostics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let live = true;
    setError(null);
    api.matchDiagnostics().then((d) => { if (live) setData(d); },
      (e) => { if (live) setError(e instanceof Error ? e.message : "Diagnostics could not be loaded."); });
    return () => { live = false; };
  }, [refresh, refreshKey]);
  return <section className="match-diagnostics" aria-label="Matching diagnostics">
    <button onClick={() => setRefresh((n) => n + 1)}>Refresh diagnostics</button>
    {error && <p className="error" role="alert">{error}</p>}
    {data && <>
      <dl>
        <dt>Usable distinct visual hashes in catalog</dt><dd>{count(data.distinct_hashes)}</dd>
        <dt>Stored pairs of different hashes</dt><dd>{count(data.stored_pairs)}</dd>
        <dt>Destination photos awaiting comparison</dt><dd>{count(data.state.pending)}</dd>
        <dt>Destination photos without usable hashes</dt><dd>{count(data.state.unavailable)}</dd>
        <dt>Last queue query on server</dt><dd>{queueMs == null ? "Not recorded" : `${queueMs} ms`}</dd>
        <dt>Last comparison phase, reported elapsed</dt><dd>{data.last_comparison ? `${data.last_comparison.elapsed_seconds.toFixed(2)} s (job ${data.last_comparison.run_id})` : "Not recorded"}</dd>
      </dl>
      <p className="muted">Equal visual hashes share a bucket and do not add stored pairs. Queue timing excludes network and image loading.</p>
    </>}
  </section>;
}
