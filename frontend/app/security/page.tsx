"use client";

import { useCallback, useEffect, useState } from "react";
import { get, post, timeAgo } from "@/lib/api";
import { Badge, Empty, ErrorBox, Panel, Spinner, Stat } from "@/components/ui";

type GuardEvent = {
  id: number; category: string; action: string; user: string;
  snippet: string; details: Record<string, any>; created_at: string;
};
type GuardStats = {
  total: number; by_category: Record<string, number>;
  by_action: Record<string, number>; guard_mode: string;
};
type AuditEntry = {
  id: number; actor: string; action: string; target: string;
  details: Record<string, any>; created_at: string;
};
type Finding = { check: string; severity: string; status: string; title: string; hint?: string };

const SEV_TONE: Record<string, string> = {
  critical: "red", high: "red", medium: "yellow", low: "yellow", info: "green",
};

export default function SecurityPage() {
  const [events, setEvents] = useState<GuardEvent[]>([]);
  const [stats, setStats] = useState<GuardStats | null>(null);
  const [log, setLog] = useState<AuditEntry[]>([]);
  const [cfg, setCfg] = useState<any>(null);
  const [err, setErr] = useState("");
  const [running, setRunning] = useState(false);
  const [audit, setAudit] = useState<{ findings: Finding[]; high_count: number; duration_s: number; light: boolean } | null>(null);
  const [auditErr, setAuditErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [e, s, l, c] = await Promise.all([
        get("/admin/security/events?limit=50"),
        get("/admin/security/stats"),
        get("/admin/security/audit-log?limit=50"),
        get("/meta/config"),
      ]);
      setEvents(e);
      setStats(s);
      setLog(l);
      setCfg(c);
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

  const runAudit = async () => {
    setRunning(true);
    setAuditErr("");
    try {
      setAudit(await post("/admin/security/audit"));
      load();
    } catch (e: any) {
      setAuditErr(String(e.message || e));
    } finally {
      setRunning(false);
    }
  };

  if (err) return <ErrorBox error={`backend unreachable — ${err}`} />;
  if (!stats) return <Spinner />;

  const strict = stats.guard_mode === "strict";

  return (
    <>
      <div className="page-title">Security</div>
      <div className="page-sub">
        input guard · prompt-injection detection · admin action audit trail · in-app security audit
      </div>

      <div className="grid grid-4 mb">
        <Stat
          num={stats.total}
          lbl="Guard events"
          sub={Object.entries(stats.by_action).map(([k, v]) => `${k}: ${v}`).join(" · ") || "none"}
          color={stats.total ? "var(--yellow)" : undefined}
        />
        <Stat
          num={stats.guard_mode}
          lbl="Guard mode"
          sub={strict ? "injections are blocked (400)" : "injections flagged + logged only"}
          color={strict ? "var(--green)" : "var(--yellow)"}
        />
        <Stat
          num={cfg?.auth_enabled ? "ON" : "OFF"}
          lbl="API auth"
          sub={`admin key ${cfg?.admin_auth_enabled ? "on" : "off"} · docs ${cfg?.docs_enabled ? "on" : "off"}`}
          color={cfg?.auth_enabled ? "var(--green)" : "var(--red)"}
        />
        <Stat num={log.length} lbl="Audit-log entries (recent)" sub="every privileged action is recorded" />
      </div>

      <div className="grid grid-2 mb">
        <Panel title="Guard events (flagged / blocked inputs)">
          {events.length === 0 ? (
            <Empty>no suspicious inputs detected yet — try an injection in chat</Empty>
          ) : (
            <table className="tbl">
              <tbody>
                {events.map((e) => (
                  <tr key={e.id}>
                    <td style={{ width: 120 }}>
                      <Badge tone={e.action === "blocked" ? "red" : "yellow"}>{e.action}</Badge>
                      <div className="mono-s faint">{e.category}</div>
                    </td>
                    <td>
                      <div className="mono-s" style={{ overflowWrap: "anywhere" }}>
                        {e.snippet}
                      </div>
                      <div className="row" style={{ gap: 6 }}>
                        <Badge tone="dim">user: {e.user || "?"}</Badge>
                        {e.details?.matched_patterns && (
                          <Badge tone="purple">{e.details.matched_patterns}</Badge>
                        )}
                      </div>
                    </td>
                    <td style={{ width: 80 }} className="faint small">{timeAgo(e.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        <Panel
          title="In-app security audit (light)"
          right={
            <button className="btn primary sm" onClick={runAudit} disabled={running}>
              {running ? <Spinner /> : "run audit"}
            </button>
          }
        >
          <div className="small dim mb">
            Runs the audit battery against this instance from the inside — rate-limit hammering and
            oversized payloads are skipped in light mode. Full battery: <code>synapseos audit</code>.
          </div>
          {auditErr && <ErrorBox error={auditErr} />}
          {audit ? (
            <>
              <div className="row mb" style={{ gap: 8 }}>
                <Badge tone={audit.high_count ? "red" : "green"}>{audit.high_count} high findings</Badge>
                <Badge tone="dim">{audit.duration_s}s</Badge>
                <Badge tone="dim">light mode</Badge>
              </div>
              <table className="tbl">
                <tbody>
                  {audit.findings.map((f, i) => (
                    <tr key={i}>
                      <td style={{ width: 90 }}><Badge tone={SEV_TONE[f.severity] || "dim"}>{f.severity}</Badge></td>
                      <td>
                        <div className="row" style={{ gap: 6 }}>
                          <span className="mono-s">{f.check}</span>
                          <Badge tone={f.status === "PASS" ? "green" : f.status === "FAIL" ? "red" : "yellow"}>{f.status}</Badge>
                        </div>
                        <div className="small">{f.title}</div>
                        {f.hint && <div className="small faint">{f.hint}</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <Empty>no audit run yet in this session</Empty>
          )}
        </Panel>
      </div>

      <Panel title="Admin audit trail — privileged actions">
        {log.length === 0 ? (
          <Empty>no privileged actions yet — approve a fact or roll back the KB</Empty>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th style={{ width: 90 }}>id</th>
                <th style={{ width: 160 }}>action</th>
                <th style={{ width: 140 }}>actor</th>
                <th>target / details</th>
                <th style={{ width: 90 }}>when</th>
              </tr>
            </thead>
            <tbody>
              {log.map((e) => (
                <tr key={e.id}>
                  <td className="faint mono-s">#{e.id}</td>
                  <td>
                    <Badge tone={e.action.startsWith("guard.") ? "yellow" : e.action.startsWith("security.") ? "purple" : "cyan"}>
                      {e.action}
                    </Badge>
                  </td>
                  <td className="small">{e.actor}</td>
                  <td>
                    <div className="small">{e.target}</div>
                    {Object.keys(e.details || {}).length > 0 && (
                      <div className="mono-s faint" style={{ whiteSpace: "pre-wrap", maxHeight: 60, overflow: "hidden" }}>
                        {JSON.stringify(e.details).slice(0, 220)}
                      </div>
                    )}
                  </td>
                  <td className="faint small">{timeAgo(e.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </>
  );
}
