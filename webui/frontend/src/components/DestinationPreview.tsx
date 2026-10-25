import { useEffect, useState } from "react";
import { api, type MoveScope, type TransferPreview, type TransferPreviewItem } from "../api";
import { Pager } from "./Pager";
import { plural } from "../format";

function Files({ items }: { items: TransferPreviewItem[] }) {
  return <ul className="destination-preview-files">{items.map(item => <li key={item.photo_id}>
    <strong>{item.filename}</strong><div className="section-note">Source: {item.source}</div>
    <div className="section-note">{item.note}</div>
  </li>)}</ul>;
}

function Folder({ group, plan, busy, onInvalid }: { group: TransferPreview["groups"][number]; plan: TransferPreview;
  busy: boolean; onInvalid: (message: string) => void }) {
  const [items, setItems] = useState(group.items);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const load = async (next: number) => {
    setLoading(true);
    try {
      const answer = await api.previewTransferFolder({ mode: plan.mode, file_ids: plan.file_ids,
        token: plan.token, folder: group.path, file_page: next });
      setItems(answer.items); setPage(next);
    } catch (e) { onInvalid(e instanceof Error ? e.message : "Could not load this folder. Refresh the preview."); }
    finally { setLoading(false); }
  };
  return <details className="destination-preview-folder"><summary><span>{group.path}</span> · {plural(group.total, "source file")}</summary>
    <Files items={items} />
    {group.total > 20 && <fieldset disabled={busy || loading} aria-label={`Files in ${group.path}`}>
      <Pager page={page} pages={Math.ceil(group.total / 20)} total={group.total} pageSize={20}
        sizes={[20]} noun="source file" onPage={next => void load(next)} onPageSize={() => {}} />
    </fieldset>}
    {loading && <p role="status">Loading filenames…</p>}
  </details>;
}

export function DestinationPreview({ mode, scope, refresh, busy, onReady, onRefresh }: {
  mode: "copy" | "move"; scope: MoveScope; refresh: number; busy: boolean;
  onReady: (plan: TransferPreview | null) => void; onRefresh: () => void;
}) {
  const [plan, setPlan] = useState<TransferPreview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [unplannedPage, setUnplannedPage] = useState(1);
  const scopeKey = JSON.stringify(scope);
  useEffect(() => {
    let live = true;
    setPlan(null); onReady(null); setError(""); setLoading(true); setUnplannedPage(1);
    api.previewTransfer({ mode, ...JSON.parse(scopeKey) }).then(value => {
      if (live) { setPlan(value); onReady(value); }
    }, e => { if (live) setError(e instanceof Error ? e.message : "Could not load destination folders."); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [mode, scopeKey, refresh, onReady]);
  const invalid = (message: string) => { setError(message); onReady(null); };
  const load = async (page: number, filePage = unplannedPage) => {
    if (!plan) return;
    setLoading(true);
    try {
      const value = await api.previewTransfer({ mode, file_ids: plan.file_ids, token: plan.token, page, file_page: filePage });
      setPlan(value); setUnplannedPage(filePage);
    } catch (e) { invalid(e instanceof Error ? e.message : "Could not load the preview."); }
    finally { setLoading(false); }
  };
  return <section className="destination-preview" aria-label="Destination folders">
    <h3>Destination folders</h3>
    <p className="section-note">Paths are relative to your destination folder. Expand a folder to see source filenames.
      The job checks files and available names before transferring; its log records what happened.</p>
    {loading && <p role="status">Checking destination folders…</p>}
    {error && <><p className="error" role="alert">{error}</p><button className="primary" disabled={busy || loading} onClick={onRefresh}>Refresh destination preview</button></>}
    {plan && <>
      <p>{plural(plan.planned, "source file")} in {plural(plan.group_total, "destination folder")}.</p>
      {plan.groups.map(group => <Folder key={`${plan.token}:${plan.page}:${group.path}`} group={group} plan={plan} busy={busy || loading || !!error} onInvalid={invalid} />)}
      {plan.group_total > plan.page_size && <fieldset disabled={busy || loading || !!error} aria-label="Destination folder pages">
        <Pager page={plan.page} pages={Math.ceil(plan.group_total / plan.page_size)} total={plan.group_total}
          pageSize={plan.page_size} sizes={[plan.page_size]} noun="folder" onPage={page => void load(page)} onPageSize={() => {}} />
      </fieldset>}
      {plan.unplanned_total > 0 && <details><summary>{plural(plan.unplanned_total, "source file")} without a proposed delivery</summary>
        <Files items={plan.unplanned} />
        {plan.unplanned_total > 20 && <fieldset disabled={busy || loading || !!error} aria-label="Photos without a proposed delivery">
          <Pager page={unplannedPage} pages={Math.ceil(plan.unplanned_total / 20)} total={plan.unplanned_total}
            pageSize={20} sizes={[20]} noun="source file" onPage={page => void load(plan.page, page)} onPageSize={() => {}} />
        </fieldset>}
      </details>}
    </>}
  </section>;
}
