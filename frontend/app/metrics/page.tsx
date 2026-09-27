"use client";

import { useCallback, useEffect, useState } from "react";
import { get } from "@/lib/api";
import { Empty, ErrorBox, Panel, Spinner } from "@/components/ui";
import { BarRow, LineChart } from "@/components/charts";
import { Badge } from "@/components/ui";

type CurvePoint = { day: string; interactions: number; avg_reward: number | null; avg_confidence: number | null; flagged: number };

export default function MetricsPage() {
  const [curve, setCurve] = useState<CurvePoint[]>([]);
  const [fb, setFb] = useState<any>(null);
  const [topics, setTopics] = useState<any[]>([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [c, f, t] = await Promise.all([
        get("/admin/metrics/learning-curve?days=60"),
        get("/admin/metrics/feedback?days=60"),
        get("/admin/metrics/topics"),
      ]);
      setCurve(c.series);
      setFb(f);
      setTopics(t.topics);
      setErr("");
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (err) return <ErrorBox error={err} />;
  if (loading) return <Spinner />;

  const maxVol = Math.max(1, ...curve.map((p) => p.interactions));
  const rewarded = curve.filter((p) => p.avg_reward !== null);
  const maxTopic = Math.max(1, ...topics.map((t) => t.interactions));

  return (
    <>
      <div className="page-title">Learning Metrics</div>
      <div className="page-sub">
        reward learning curve · feedback statistics · per-topic reinforcement signals —
        all derived from the structured interaction ledger
      </div>

      <Panel title="Learning curve — average reward & confidence per day">
        <LineChart
          height={220}
          series={[
            { name: "avg reward", color: "var(--green)", points: rewarded.map((p) => ({ x: p.day, y: p.avg_reward })) },
            { name: "avg confidence", color: "var(--cyan)", points: curve.map((p) => ({ x: p.day, y: p.avg_confidence })), dashed: true },
          ]}
          yMin={-1}
          yMax={1}
        />
      </Panel>

      <Panel title="Interaction volume & flagged answers">
        <LineChart
          height={160}
          series={[
            { name: "interactions/day", color: "var(--purple)", points: curve.map((p) => ({ x: p.day, y: p.interactions })) },
            { name: "flagged (low confidence)", color: "var(--red)", points: curve.map((p) => ({ x: p.day, y: p.flagged })) },
          ]}
          yMin={0}
        />
      </Panel>

      <div className="grid grid-2">
        <Panel title="Feedback by day (normalized reward)">
          {!fb || Object.keys(fb.by_day || {}).length === 0 ? (
            <Empty>no feedback yet</Empty>
          ) : (
            <div style={{ maxHeight: 300, overflowY: "auto" }}>
              {Object.entries(fb.by_day).sort().slice(-25).map(([day, kinds]: [string, any]) => (
                <div key={day} className="trace-step">
                  <div className="spread">
                    <span className="small dim">{day}</span>
                    <span className="row" style={{ gap: 6 }}>
                      {Object.entries(kinds).map(([k, v]: [string, any]) => (
                        <Badge key={k} tone={k === "correction" ? "yellow" : k === "thumb" ? "cyan" : "purple"}>
                          {k} ×{v.count} (r̄ {v.avg_reward?.toFixed(2)})
                        </Badge>
                      ))}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
          {fb?.totals && (
            <>
              <hr className="sep" />
              <div className="row" style={{ gap: 10 }}>
                {Object.entries(fb.totals).map(([k, v]) => (
                  <Badge key={k} tone="dim">{k}: {v as number}</Badge>
                ))}
              </div>
            </>
          )}
        </Panel>

        <Panel title="Per-topic reinforcement signal">
          {topics.length === 0 ? (
            <Empty />
          ) : (
            <>
              {topics.map((t) => (
                <div key={t.topic} style={{ marginBottom: 12 }}>
                  <BarRow
                    label={t.topic}
                    value={t.interactions}
                    max={maxTopic}
                    color="var(--purple)"
                    right={`${t.interactions} int`}
                  />
                  <div className="row small" style={{ gap: 14, paddingLeft: 160 }}>
                    <span className="dim">
                      reward EMA{" "}
                      <span style={{ color: (t.reward_ema ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                        {t.reward_ema?.toFixed(3) ?? "—"}
                      </span>
                    </span>
                    <span className="dim">avg reward {t.avg_reward?.toFixed(3) ?? "—"}</span>
                    <span className="dim">conf {(t.avg_confidence * 100)?.toFixed(0) ?? "—"}%</span>
                  </div>
                </div>
              ))}
            </>
          )}
        </Panel>
      </div>
    </>
  );
}
