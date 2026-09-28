"use client";

import { useCallback, useEffect, useState } from "react";
import { get, post } from "@/lib/api";
import { Badge, Empty, ErrorBox, Panel, Spinner } from "@/components/ui";

type Fact = {
  id: number; statement: string; status: string; version: number;
  proposed_by: string; decided_by: string; created_at: string;
  evidence?: Record<string, any>;
};
type Version = { id: number; label: string; note: string; created_by: string; facts: number; documents: number; created_at: string };
type Doc = { id: number; title: string; source: string; modality: string; active: boolean; chars: number; created_at: string };

export default function KnowledgePage() {
  const [facts, setFacts] = useState<Fact[]>([]);
  const [versions, setVersions] = useState<Version[]>([]);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<"active" | "pending" | "rejected" | "retired">("pending");
  const [q, setQ] = useState("");
  const [kinds, setKinds] = useState<string[]>([]);
  const [results, setResults] = useState<any[] | null>(null);
  const [searching, setSearching] = useState(false);

  const load = useCallback(async () => {
    try {
      const [f, v, d] = await Promise.all([
        get("/kb/facts"),
        get("/kb/versions"),
        get("/documents"),
      ]);
      setFacts(f);
      setVersions(v);
      setDocs(d);
      setErr("");
    } catch (e: any) {
      setErr(String(e.message || e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const search = async () => {
    if (!q.trim()) return;
    setSearching(true);
    try {
      const body: any = { text: q, top_k: 10 };
      if (kinds.length > 0) body.kinds = kinds;
      const r = await post("/search", body);
      setResults(r.results);
      setErr("");
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setSearching(false);
    }
  };

  const toggleKind = (k: string) =>
    setKinds((ks) => (ks.includes(k) ? ks.filter((x) => x !== k) : [...ks, k]));

  const addDoc = async () => {
    if (!title.trim() || !body.trim()) return;
    setBusy(true);
    try {
      const r = await post("/documents", { title, text: body, source: "dashboard" });
      setNote(`Ingested “${r.title}” — ${r.chunks} chunks embedded. Version ${versions[0]?.id ?? 1}+ created.`);
      setTitle("");
      setBody("");
      await load();
    } catch (e: any) {
      setNote(`⚠ ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const uploadDoc = async () => {
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("title", file.name);
      const r = await fetch("/backend-api/documents/upload", { method: "POST", body: fd });
      if (!r.ok) throw new Error(await r.text());
      const j = await r.json();
      setNote(`Uploaded “${j.title}” (${j.modality}) — document #${j.id}.`);
      setFile(null);
      await load();
    } catch (e: any) {
      setNote(`⚠ ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const deactivate = async (id: number) => {
    setBusy(true);
    try {
      await fetch(`/backend-api/documents/${id}`, { method: "DELETE" });
      setNote(`Document #${id} deactivated (reversible via rollback).`);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const decide = async (id: number, approve: boolean) => {
    setBusy(true);
    try {
      await post(`/kb/facts/${id}/${approve ? "approve" : "reject"}`, {});
      setNote(`Fact #${id} ${approve ? "approved — live in retrieval" : "rejected"}.`);
      await load();
    } catch (e: any) {
      setNote(`⚠ ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const rollback = async (id: number) => {
    setBusy(true);
    try {
      const r = await post(`/kb/versions/${id}/rollback`, {});
      setNote(`Rolled back to version ${id} — new version ${r.new_version} created.`);
      await load();
    } catch (e: any) {
      setNote(`⚠ ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const byStatus = (s: string) => facts.filter((f) => f.status === s);

  return (
    <>
      <div className="page-title">Knowledge Base</div>
      <div className="page-sub">
        documents + approved learned facts feed retrieval · every change creates an immutable
        version · roll back any bad “learned” update
      </div>
      <Panel
        title="Semantic search — one query across documents, chunks, facts and memories"
        right={
          <div className="row" style={{ gap: 6 }}>
            {["document", "chunk", "fact", "memory"].map((k) => (
              <button
                key={k}
                className={`btn sm ${kinds.includes(k) ? "primary" : "ghost"}`}
                onClick={() => toggleKind(k)}
              >
                {k}
              </button>
            ))}
          </div>
        }
      >
        <div className="row" style={{ alignItems: "flex-end" }}>
          <div style={{ flex: 1 }}>
            <input
              value={q}
              placeholder="search meaning, not keywords — e.g. “how does the reward model learn?”"
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && search()}
            />
          </div>
          <button className="btn primary" onClick={search} disabled={searching || !q.trim()}>
            {searching ? <Spinner /> : "search ▸"}
          </button>
        </div>
        {results && (
          <>
            <hr className="sep" />
            {results.length === 0 ? (
              <Empty>no matches</Empty>
            ) : (
              results.map((r, i) => (
                <div key={i} className="src">
                  <Badge tone={r.kind === "fact" ? "cyan" : r.kind === "memory" ? "purple" : "dim"}>{r.kind}</Badge>
                  <div style={{ flex: 1 }}>
                    <div className="small">{r.title}</div>
                    <div className="mono-s faint">{(r.text || "").slice(0, 160)}…</div>
                  </div>
                  <span className="mono-s dim">{r.score?.toFixed(3)}</span>
                </div>
              ))
            )}
            <div className="small faint mt">{results.length} result(s)</div>
          </>
        )}
      </Panel>

      {note && <div className="badge b-cyan mb" style={{ display: "block", padding: 8 }}>{note}</div>}
      {err && <ErrorBox error={err} />}

      <div className="grid grid-2">
        <Panel title="Ingest document">
          <label className="field">Title</label>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Internal runbook" />
          <div className="mt" />
          <label className="field">Content</label>
          <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={5}
            placeholder="Paste knowledge here. It will be chunked and embedded into the vector store." />
          <div className="row mt">
            <button className="btn primary" onClick={addDoc} disabled={busy || !title.trim() || !body.trim()}>
              ingest &amp; embed ▸
            </button>
          </div>
          <hr className="sep" />
          <label className="field">Or upload a file (txt/md → text · image → captioned KB entry · audio)</label>
          <div className="row">
            <input type="file" onChange={(e) => setFile(e.target.files?.[0] || null)} style={{ fontSize: 11 }} />
            <button className="btn" onClick={uploadDoc} disabled={busy || !file}>upload</button>
          </div>
        </Panel>

        <Panel title={`Documents — ${docs.filter((d) => d.active).length} active`}>
          {docs.length === 0 ? (
            <Empty />
          ) : (
            <div style={{ maxHeight: 330, overflowY: "auto" }}>
              <table className="tbl">
                <tbody>
                  {docs.map((d) => (
                    <tr key={d.id}>
                      <td>
                        <div>{d.title}</div>
                        <span className="faint mono-s">{d.source} · {d.chars} chars</span>
                      </td>
                      <td style={{ width: 70 }}>
                        <Badge tone={d.modality === "text" ? "dim" : d.modality === "image" ? "purple" : "cyan"}>{d.modality}</Badge>
                      </td>
                      <td style={{ width: 90 }}>
                        {d.active ? (
                          <button className="btn sm ghost" disabled={busy} onClick={() => deactivate(d.id)}>deactivate</button>
                        ) : (
                          <Badge tone="yellow">inactive</Badge>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>

      <Panel
        title={`Learned facts — ${facts.length} total`}
        right={
          <div className="row">
            {(["pending", "active", "rejected", "retired"] as const).map((s) => (
              <button key={s} className={`btn sm ${tab === s ? "primary" : "ghost"}`} onClick={() => setTab(s)}>
                {s} ({byStatus(s).length})
              </button>
            ))}
          </div>
        }
      >
        {byStatus(tab).length === 0 ? (
          <Empty>no {tab} facts</Empty>
        ) : (
          <table className="tbl">
            <tbody>
              {byStatus(tab).map((f) => (
                <tr key={f.id}>
                  <td style={{ width: 46 }} className="faint">#{f.id}</td>
                  <td>
                    <div>{f.statement}</div>
                    <span className="faint mono-s">
                      proposed by {f.proposed_by}
                      {f.decided_by ? ` · decided by ${f.decided_by}` : ""} · {new Date(f.created_at).toLocaleDateString()}
                    </span>
                  </td>
                  <td style={{ width: 150 }}>
                    {f.status === "pending" && (
                      <div className="row">
                        <button className="btn good sm" disabled={busy} onClick={() => decide(f.id, true)}>✓ approve</button>
                        <button className="btn bad sm" disabled={busy} onClick={() => decide(f.id, false)}>✗</button>
                      </div>
                    )}
                    {f.status === "active" && <Badge tone="green">live · v{f.version}</Badge>}
                    {f.status === "rejected" && <Badge tone="red">rejected</Badge>}
                    {f.status === "retired" && <Badge tone="dim">retired (rollback)</Badge>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title={`Version history — ${versions.length} versions (rollback available)`}>
        {versions.length === 0 ? (
          <Empty />
        ) : (
          <div style={{ maxHeight: 300, overflowY: "auto" }}>
            <table className="tbl">
              <thead>
                <tr>
                  <th style={{ width: 60 }}>Version</th>
                  <th>Change</th>
                  <th style={{ width: 110 }}>State</th>
                  <th style={{ width: 100 }}></th>
                </tr>
              </thead>
              <tbody>
                {versions.map((v) => (
                  <tr key={v.id}>
                    <td className="faint">v{v.id}</td>
                    <td>
                      <div>{v.label}</div>
                      <span className="faint mono-s">{v.facts} facts · {v.documents} docs · {new Date(v.created_at).toLocaleString()}</span>
                    </td>
                    <td className="mono-s dim">{v.facts}F / {v.documents}D</td>
                    <td>
                      {v.id !== versions[0].id && (
                        <button className="btn sm" disabled={busy} onClick={() => rollback(v.id)}>⟲ rollback here</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}
