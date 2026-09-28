"use client";

import { useCallback, useEffect, useState } from "react";
import { get, post } from "@/lib/api";
import { Badge, Empty, ErrorBox, Panel, Spinner } from "@/components/ui";

type ReviewItem = {
  id: number;
  kind: "low_confidence" | "fact" | "drift";
  ref_id: number | null;
  reason: string;
  payload: any;
  status: string;
  created_at: string;
};

export default function ReviewPage() {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [err, setErr] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    try {
      setItems(await get("/admin/review?status=open"));
      setErr("");
    } catch (e: any) {
      setErr(String(e.message || e));
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [load]);

  const resolve = async (id: number, decision: string) => {
    setBusyId(id);
    try {
      await post(`/admin/review/${id}/resolve`, { decision });
      await load();
    } catch (e: any) {
      setNote(`⚠ ${e.message}`);
    } finally {
      setBusyId(null);
    }
  };

  const decideFact = async (factId: number, approve: boolean, reviewId: number) => {
    setBusyId(reviewId);
    try {
      await post(`/kb/facts/${factId}/${approve ? "approve" : "reject"}`, {});
      setNote(
        approve
          ? `Fact #${factId} approved — it is now live in the knowledge base (new KB version created).`
          : `Fact #${factId} rejected.`,
      );
      await load();
    } catch (e: any) {
      setNote(`⚠ ${e.message}`);
    } finally {
      setBusyId(null);
    }
  };

  const lowConf = items.filter((i) => i.kind === "low_confidence");
  const facts = items.filter((i) => i.kind === "fact");
  const drifts = items.filter((i) => i.kind === "drift");

  return (
    <>
      <div className="page-title">Human-in-the-Loop Review</div>
      <div className="page-sub">
        low-confidence answers and learned facts wait here before influencing the system —
        approve ✓ to make knowledge live, reject ✗ to discard
      </div>
      {note && <div className="badge b-cyan mb" style={{ display: "block", padding: 8 }}>{note}</div>}
      {err && <ErrorBox error={err} />}

      <Panel title={`Learned fact proposals — ${facts.length} pending`}>
        {facts.length === 0 ? (
          <Empty>no pending fact proposals (submit a correction in chat to create one)</Empty>
        ) : (
          facts.map((f) => (
            <div key={f.id} className="panel" style={{ background: "var(--bg-soft)", marginBottom: 10 }}>
              <div className="spread">
                <div>
                  <Badge tone="cyan">proposed fact</Badge>{" "}
                  <span className="faint mono-s">{new Date(f.created_at).toLocaleString()}</span>
                </div>
                <div className="row">
                  <button className="btn good sm" disabled={busyId === f.id} onClick={() => decideFact(f.ref_id!, true, f.id)}>
                    ✓ approve &amp; publish
                  </button>
                  <button className="btn bad sm" disabled={busyId === f.id} onClick={() => decideFact(f.ref_id!, false, f.id)}>
                    ✗ reject
                  </button>
                </div>
              </div>
              <div className="mt small" style={{ fontSize: 13 }}>{f.payload?.statement}</div>
              {f.payload?.evidence && (
                <div className="mono-s faint mt">
                  evidence: Q:“{(f.payload.evidence.original_question || "").slice(0, 90)}” ·
                  original answer:“{(f.payload.evidence.original_answer || "").slice(0, 90)}…” ·
                  by {f.payload.evidence.user}
                </div>
              )}
            </div>
          ))
        )}
      </Panel>

      <Panel title={`Low-confidence answers — ${lowConf.length} flagged by the self-evaluator`}>
        {lowConf.length === 0 ? (
          <Empty>no low-confidence answers waiting</Empty>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Question</th>
                <th>Answer</th>
                <th style={{ width: 150 }}>Critique</th>
                <th style={{ width: 120 }}></th>
              </tr>
            </thead>
            <tbody>
              {lowConf.map((i) => (
                <tr key={i.id}>
                  <td>
                    <div>{i.payload?.question?.slice(0, 140)}</div>
                    <span className="faint mono-s">{i.reason}</span>
                  </td>
                  <td className="dim small">{i.payload?.answer?.slice(0, 180)}…</td>
                  <td className="mono-s">
                    <div>conf {i.payload?.critique?.confidence}</div>
                    <div className="faint">{i.payload?.critique?.notes?.[0]}</div>
                  </td>
                  <td>
                    <div className="row">
                      <button className="btn sm" disabled={busyId === i.id} onClick={() => resolve(i.id, "resolved")}>
                        reviewed ✓
                      </button>
                      <button className="btn ghost sm" disabled={busyId === i.id} onClick={() => resolve(i.id, "dismissed")}>
                        dismiss
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title={`Critical drift events — ${drifts.length}`}>
        {drifts.length === 0 ? (
          <Empty>no critical drift events</Empty>
        ) : (
          drifts.map((d) => (
            <div key={d.id} className="row spread" style={{ padding: 8, borderBottom: "1px solid var(--border-soft)" }}>
              <div>
                <Badge tone="red">{d.reason}</Badge>
                <span className="mono-s dim"> {JSON.stringify(d.payload).slice(0, 140)}</span>
              </div>
              <button className="btn sm" onClick={() => resolve(d.id, "resolved")}>acknowledge</button>
            </div>
          ))
        )}
      </Panel>
    </>
  );
}
