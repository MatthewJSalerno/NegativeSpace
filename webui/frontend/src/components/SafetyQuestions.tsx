import { useState } from "react";
import { api, type Run, type SafetyAnswer, type SafetyQuestion } from "../api";
import { ConfirmDialog, type Confirm } from "./Confirm";

export function SafetyQuestions({ run, onLeave }: { run: Run; onLeave: () => void }) {
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const scope = typeof run.targeting?.selection === "number"
    ? `${run.targeting.selection.toLocaleString()} selected photos`
    : typeof run.targeting?.source_subdir === "string"
      ? `folder “${run.targeting.source_subdir}” and its subfolders` : "the whole source";
  const ask = (question: SafetyQuestion, answer: SafetyAnswer, title: string, body: string[], danger = false) => {
    setConfirm({ title, body: [...body, `This starts a new job for the original scope: ${scope}.`],
      action: answer === "confirm_move" ? "Confirm and Move" : answer === "copy" ? "Copy instead"
        : answer === "retry" ? "Retry original job" : "Confirm empty source", danger,
      run: async () => {
        await api.answerQuestion(run.id!, question, answer);
        setSubmitted(true);
      },
    });
  };
  if (!run.questions?.length) return null;
  return <section className="safety-questions" aria-label="Job needs a decision">
    <p>Job #{run.id} needs a decision · Original scope: {scope}.</p>
    {run.questions.includes("source_empty") && <div>
      <strong>The source appears empty. Is its storage disconnected, or is it really empty?</strong>
      <p>Reconnect missing storage before retrying. Confirming empty lets the engine record missing sources and verify any copies at the destination.</p>
      <button disabled={submitted} onClick={() => ask("source_empty", "retry", "Retry after reconnecting?",
        ["Check that the intended source storage is connected. No empty-source confirmation will be added."])}>I reconnected it — retry</button>{" "}
      <button disabled={submitted} onClick={() => ask("source_empty", "confirm_empty", "Confirm the source is really empty?",
        ["Confirm only after checking the intended source folder. This updates catalog observations; existing history is retained."])}>It really is empty</button>
    </div>}
    {run.questions.includes("network_destination") && <div>
      <strong>The destination is on network storage. Choose how to continue.</strong>
      <p>Network storage may acknowledge a save before it is durable. Copy keeps the originals and is recommended.</p>
      <button className="primary" disabled={submitted} onClick={() => ask("network_destination", "copy", "Copy instead of Move?",
        ["Copy verifies the destination and keeps every original."])}>Copy instead (recommended)</button>{" "}
      <button disabled={submitted} onClick={() => ask("network_destination", "confirm_move", "Confirm network storage before Move",
        ["Confirm that the network share is exported synchronously (sync) and honors durable writes. NegativeSpace cannot verify that configuration.",
         "Move deletes each original after verifying its destination copy. Proceed only if you accept the storage durability risk."], true)}>Move anyway…</button>
    </div>}
    <p><button disabled={submitted} onClick={onLeave}>Leave unchanged</button></p>
    {submitted && <p role="status">Answer accepted. Waiting for the new job status…</p>}
    {confirm && <ConfirmDialog confirm={confirm} onClose={() => setConfirm(null)} />}
  </section>;
}
