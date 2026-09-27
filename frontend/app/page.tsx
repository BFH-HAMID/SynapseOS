"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { get } from "@/lib/api";
import { Badge, Confidence, Empty, ErrorBox, Panel, Spinner, Stat } from "@/components/ui";
import { BarRow, LineChart } from "@/components/charts";

type Overview = {
  totals: Record<string, number>;
  averages: Record<string, number>;
  feedback_by_kind: Record<string, number>;
  reward_model: { emas: Record<string, number>; policy: Record<string, any> };
  vector_store: Record<string, number>;
  drift_current: { status?: string; psi?: number | null };
};
type CurvePoint = { day: string; interactions: number; avg_reward: number | null; avg_confidence: number | null; flagged: number };

export default function OverviewPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [curve, setCurve] = useState<CurvePoint[]>([]);
  const [recent, setRecent] = useState<any[]>([]);
  const [err, setErr] = useState("");
  const [cfg, setCfg] = useState<any>(null);

  const load = useCallback(async () => {
    try {
      const [o, c, r, cf] = await Promise.all([
        get("/admin/overview"),
        get("/admin/metrics/learning-curve?days=30"),
        get("/admin/interactions?limit=6"),
        get("/meta/config"),
      ]);
      setData(o);
      setCurve(c.series);
      setRecent(r);
      setCfg(cf);
      setErr("");
    } catch (e: any) {
      setErr(String(e.message || e));
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [load]);

  if (err) return <ErrorBox error={`backend unreachable — ${err}`} />;
  if (!data) return <Spinner />;

  const t = data.totals;
  const maxKind = Math.max(1, ...Object.values(data.feedback_by_kind));

  return (
    <>
      <div className="page-title">System Overview</div>
      <div className="page-sub">
        continuous learning loop · {cfg?.model_provider} provider ·{" "}
        {cfg?.auth_enabled ? "API auth ON" : "dev mode (no auth)"} ·{" "}
        {cfg?.vector_backend} vector store
      </div>

      <div className="grid grid-4 mb">
        <Stat num={t.interactions} lbl="Interactions" sub={`avg conf ${(data.averages.confidence * 100).toFixed(0)}%`} />
        <Stat num={t.feedback} lbl="Feedback events" sub={`avg reward ${data.averages.reward?.toFixed(2)}`} color={data.averages.reward >= 0 ? "var(--green)" : "var(--red)"} />
        <Stat num={t.open_reviews} lbl="Open reviews" sub={`${t.facts_pending} facts pending`} color={t.open_reviews ? "var(--yellow)" : undefined} />
        <Stat num={t.drift_events} lbl="Drift alerts" sub={data.drift_current?.psi != null ? `PSI ${data.drift_current.psi}` : "—"} color={t.drift_events ? "var(--red)" : undefined} />
      </div>

      <div className="grid grid-4 mb">
        <Stat num={t.documents} lbl="Documents" sub={`${data.vector_store.kb ?? 0} vectors`} />
        <Stat num={t.facts_active} lbl="Learned facts live" sub={`${t.facts_pending} pending`} color="var(--cyan)" />
        <Stat num={t.users} lbl="Users" sub="personalized profiles" />
        <Stat num={`${data.averages.latency_ms?.toFixed(0)}ms`} lbl="Avg latency" sub={`${t.flagged} flagged low-confidence`} />
      </div>

      <Panel title="Learning curve — reward over time" right={<Link className="small" href="/metrics">details →</Link>}>
        <LineChart
          series={[
            { name: "avg daily reward", color: "var(--green)", points: curve.map((p) => ({ x: p.day, y: p.avg_reward })) },
            { name: "avg confidence", color: "var(--cyan)", points: curve.map((p) => ({ x: p.day, y: p.avg_confidence })), dashed: true },
          ]}
          yMin={-1}
          yMax={1}
        />
      </Panel>

      <div className="grid grid-2">
        <Panel title="Feedback mix (all time)">
          {Object.keys(data.feedback_by_kind).length === 0 ? (
            <Empty>no feedback yet</Empty>
          ) : (
            Object.entries(data.feedback_by_kind).map(([k, v]) => (
              <BarRow key={k} label={k} value={v} max={maxKind}
                color={k === "correction" ? "var(--yellow)" : k === "thumb" ? "var(--cyan)" : "var(--purple)"} />
            ))
          )}
          <hr className="sep" />
          <div className="kv">
            <dt>reward EMA (global)</dt>
            <dd style={{ color: data.reward_model.emas.global >= 0 ? "var(--green)" : "var(--red)" }}>
              {data.reward_model.emas.global ?? "—"}
            </dd>
            <dt>policy verbosity</dt>
            <dd>{data.reward_model.policy.verbosity ?? 1.0}</dd>
            <dt>corrections seen</dt>
            <dd>{data.reward_model.policy.corrections_seen ?? 0}</dd>
          </div>
        </Panel>

        <Panel title="Recent interactions" right={<Link className="small" href="/chat">open chat →</Link>}>
          {recent.length === 0 ? (
            <Empty />
          ) : (
            <table className="tbl">
              <tbody>
                {recent.map((i) => (
                  <tr key={i.id}>
                    <td style={{ width: 34 }} className="faint">#{i.id}</td>
                    <td>
                      <div>{i.input || <span className="faint">[attachment]</span>}</div>
                      <div className="row" style={{ gap: 6 }}>
                        <Badge tone={i.flagged ? "red" : "green"}>{i.flagged ? "flagged" : "ok"}</Badge>
                        <Badge tone="dim">{i.topic}</Badge>
                        {i.reward !== null && (
                          <Badge tone={i.reward >= 0 ? "green" : "red"}>reward {i.reward?.toFixed(2)}</Badge>
                        )}
                      </div>
                    </td>
                    <td style={{ width: 130 }}><Confidence value={i.confidence} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>

      <Panel title="Engine internals">
        <div className="grid grid-4">
          <div>
            <div className="lbl small faint">VECTOR STORE</div>
            {Object.entries(data.vector_store).map(([k, v]) => (
              <div key={k} className="small dim">{k}: {v}</div>
            ))}
          </div>
          <div>
            <div className="lbl small faint">TOPIC REWARD EMAs</div>
            {Object.entries(data.reward_model.emas).filter(([k]) => k !== "global").map(([k, v]) => (
              <div key={k} className="small" style={{ color: v >= 0 ? "var(--green)" : "var(--red)" }}>{k}: {v}</div>
            ))}
          </div>
          <div>
            <div className="lbl small faint">SECURITY</div>
            <div className="small dim">auth: {cfg?.auth_enabled ? "on" : "off"}</div>
            <div className="small dim">admin key: {cfg?.admin_auth_enabled ? "on" : "off"}</div>
            <div className="small dim">docs: {cfg?.docs_enabled ? "on" : "off"}</div>
            <div className="small dim">rate limit: {cfg?.rate_limit?.capacity}/burst</div>
          </div>
          <div>
            <div className="lbl small faint">SECURITY AUDIT</div>
            <div className="small dim">run from a terminal:</div>
            <code className="small">synapseos audit</code>
            <div className="small faint mt">Parrot/Kali-friendly pentest of this instance</div>
          </div>
        </div>
      </Panel>
    </>
  );
}
