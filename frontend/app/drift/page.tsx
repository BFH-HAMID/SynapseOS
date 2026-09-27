"use client";

import { useCallback, useEffect, useState } from "react";
import { get, post } from "@/lib/api";
import { Badge, Empty, ErrorBox, Panel, Spinner, Stat } from "@/components/ui";

type Event = {
  id: number; kind: string; severity: string; details: Record<string, any>;
  resolved: boolean; created_at: string;
};
type Status = {
  psi: { status: string; psi?: number | null; n_queries?: number; message?: string };
  reward: { status: string; drop?: number; global_ema?: number; baseline_7d?: number; message?: string };
  volume: { status: string; z_score?: number; message?: string };
};

export default function DriftPage() {
  const [events, setEvents] = useState<Event[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    try {
      const [e] = await Promise.all([
        get("/admin/drift/events?limit=100"),
        get("/admin/drift/status").catch(() => null),
      ]);
      setEvents(e);
      setStatus(null); // status computed on demand (it runs full checks)
      setErr("");
    } catch (e2: any) {
      setErr(String(e2.message || e2));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const recompute = async () => {
    setBusy(true);
    try {
      setStatus(await post("/admin/drift/recompute"));
      setEvents(await get("/admin/drift/events?limit=100"));
    } catch (e: any) {
      setNote(`⚠ ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const tone = (s?: string) => (s === "ok" ? "green" : s === "insufficient_data" ? "dim" : "red");

  return (
    <>
      <div className="page-title">Drift & Anomaly Detection</div>
      <div className="page-sub">
        input-distribution PSI · reward-EMA degradation · volume anomalies — alerts fire when the
        world shifts under the model
      </div>
      {note && <div className="badge b-cyan mb" style={{ display: "block", padding: 8 }}>{note}</div>}
      {err && <ErrorBox error={err} />}

      <Panel
        title="Detector status"
        right={
          <button className="btn primary sm" onClick={recompute} disabled={busy}>
            {busy ? <Spinner /> : "run checks now ▸"}
          </button>
        }
      >
        {status ? (
          <div className="grid grid-3">
            <Stat
              num={<Badge tone={tone(status.psi.status)}>{status.psi.status}</Badge>}
              lbl="Input drift (PSI)"
              sub={`psi ${status.psi.psi ?? "—"} · ${status.psi.n_queries ?? "?"} queries`}
            />
            <Stat
              num={<Badge tone={tone(status.reward.status)}>{status.reward.status}</Badge>}
              lbl="Reward degradation"
              sub={`drop ${status.reward.drop ?? "—"} · ema ${status.reward.global_ema ?? "—"}`}
            />
            <Stat
              num={<Badge tone={tone(status.volume.status)}>{status.volume.status}</Badge>}
              lbl="Volume anomaly"
              sub={`z-score ${status.volume.z_score ?? "—"}`}
            />
          </div>
        ) : (
          <div className="empty">press “run checks now” to evaluate current drift (also runs automatically every 60s)</div>
        )}
      </Panel>

      <Panel title={`Event log — ${events.length}`}>
        {events.length === 0 ? (
          <Empty>no drift events recorded</Empty>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th style={{ width: 60 }}>ID</th>
                <th style={{ width: 90 }}>Kind</th>
                <th style={{ width: 90 }}>Severity</th>
                <th>Details</th>
                <th style={{ width: 130 }}>When</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id}>
                  <td className="faint">#{e.id}</td>
                  <td><Badge tone={e.kind === "psi" ? "cyan" : e.kind === "reward" ? "yellow" : "purple"}>{e.kind}</Badge></td>
                  <td><Badge tone={e.severity === "critical" ? "red" : e.severity === "warning" ? "yellow" : "dim"}>{e.severity}</Badge></td>
                  <td>
                    <div className="small">{e.details?.message}</div>
                    <span className="mono-s faint">{JSON.stringify(e.details).slice(0, 160)}</span>
                  </td>
                  <td className="mono-s dim">{new Date(e.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </>
  );
}
