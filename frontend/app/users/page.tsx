"use client";

import { useCallback, useEffect, useState } from "react";
import { get } from "@/lib/api";
import { Badge, Empty, ErrorBox, Panel, Spinner } from "@/components/ui";

type User = {
  id: number; ext_id: string; name: string; interactions: number;
  profile: {
    verbosity_pref: number;
    topic_affinity: Record<string, number>;
    liked_topics: Record<string, number>;
    disliked_topics: Record<string, number>;
    feedback_count: number;
    corrections_received: number;
  };
};

export default function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      setUsers(await get("/users"));
      setErr("");
    } catch (e: any) {
      setErr(String(e.message || e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    get(`/users/${encodeURIComponent(selected)}/profile`)
      .then(setDetail)
      .catch((e) => setErr(String(e.message || e)));
  }, [selected]);

  if (err) return <ErrorBox error={err} />;

  return (
    <>
      <div className="page-title">Users & Personalization Profiles</div>
      <div className="page-sub">
        each account carries a learned profile: topic affinities, verbosity preference,
        correction history — retrieval and generation adapt per user
      </div>

      <Panel title={`Users — ${users.length}`}>
        {users.length === 0 ? (
          <Empty />
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>User</th>
                <th style={{ width: 110 }}>Interactions</th>
                <th style={{ width: 110 }}>Feedback</th>
                <th style={{ width: 110 }}>Corrections</th>
                <th style={{ width: 120 }}>Verbosity pref</th>
                <th style={{ width: 90 }}></th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} style={{ cursor: "pointer" }} onClick={() => setSelected(u.ext_id)}>
                  <td>
                    <div>{u.name}</div>
                    <span className="faint mono-s">{u.ext_id}</span>
                  </td>
                  <td>{u.interactions}</td>
                  <td>{u.profile.feedback_count}</td>
                  <td>{u.profile.corrections_received}</td>
                  <td className="mono-s">×{u.profile.verbosity_pref?.toFixed(2)}</td>
                  <td>{selected === u.ext_id ? <Badge tone="cyan">selected</Badge> : <span className="faint small">view ▸</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      {selected && (
        <Panel title={`Profile — ${selected}`} right={<button className="btn ghost sm" onClick={() => setSelected(null)}>close</button>}>
          {!detail ? (
            <Spinner />
          ) : (
            <>
              <div className="grid grid-3 mb">
                <div className="panel" style={{ background: "var(--bg-soft)" }}>
                  <div className="lbl small faint">TOPIC AFFINITY (EMA)</div>
                  {Object.entries(detail.profile.topic_affinity || {}).map(([k, v]) => (
                    <div key={k} className="small spread">
                      <span className="dim">{k}</span>
                      <span style={{ color: (v as number) >= 0 ? "var(--green)" : "var(--red)" }}>{(v as number).toFixed(3)}</span>
                    </div>
                  ))}
                </div>
                <div className="panel" style={{ background: "var(--bg-soft)" }}>
                  <div className="lbl small faint">LIKED TOPICS</div>
                  {Object.keys(detail.profile.liked_topics || {}).length === 0 && <span className="faint small">—</span>}
                  {Object.entries(detail.profile.liked_topics || {}).map(([k, v]) => (
                    <div key={k} className="small spread"><span className="dim">{k}</span><span className="badge b-green">{v as number} 👍</span></div>
                  ))}
                  <hr className="sep" />
                  <div className="lbl small faint">DISLIKED</div>
                  {Object.keys(detail.profile.disliked_topics || {}).length === 0 && <span className="faint small">—</span>}
                  {Object.entries(detail.profile.disliked_topics || {}).map(([k, v]) => (
                    <div key={k} className="small spread"><span className="dim">{k}</span><span className="badge b-red">{v as number} 👎</span></div>
                  ))}
                </div>
                <div className="panel" style={{ background: "var(--bg-soft)" }}>
                  <div className="lbl small faint">LONG-TERM MEMORIES ({detail.memories?.length ?? 0})</div>
                  <div style={{ maxHeight: 210, overflowY: "auto" }}>
                    {(detail.memories || []).map((m: any) => (
                      <div key={m.id} className="trace-step">
                        <Badge tone={m.kind === "correction" ? "yellow" : m.kind === "preference" ? "purple" : "dim"}>{m.kind}</Badge>
                        <div className="mono-s dim">{m.text.slice(0, 110)}</div>
                      </div>
                    ))}
                    {(detail.memories || []).length === 0 && <span className="faint small">—</span>}
                  </div>
                </div>
              </div>
              <a className="small" href="#" onClick={(e) => { e.preventDefault(); window.open(`/backend-api/users/${selected}/history`, "_blank"); }}>
                full interaction history (JSON) ↗
              </a>
            </>
          )}
        </Panel>
      )}
    </>
  );
}
