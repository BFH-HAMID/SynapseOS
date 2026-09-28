"use client";

import { useEffect, useRef, useState } from "react";
import { post } from "@/lib/api";
import { Badge, Confidence, Panel, Spinner } from "@/components/ui";

type Source = { type: string; title: string; snippet: string; score: number };
type TraceStep = { step: string; detail: Record<string, any> };
type Msg = {
  role: "user" | "assistant";
  content: string;
  interactionId?: number;
  confidence?: number;
  verdict?: string;
  flagged?: boolean;
  sources?: Source[];
  trace?: TraceStep[];
  model?: string;
  topic?: string;
  reward?: number | null;
  attachments?: { name: string; kind: string; desc?: string }[];
  suggestions?: string[];
  blocked?: boolean;
  blockReasons?: string[];
  guardFlagged?: boolean;
};

const USERS = ["alice", "bob", "carol"];

export default function ChatPage() {
  const [user, setUser] = useState("alice");
  const [session, setSession] = useState("web-1");
  const [text, setText] = useState("");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [openExplain, setOpenExplain] = useState<number | null>(null);
  const [correctionFor, setCorrectionFor] = useState<number | null>(null);
  const [correctionText, setCorrectionText] = useState("");
  const [notice, setNotice] = useState("");
  const [attachment, setAttachment] = useState<{ file: File; kind: string; preview?: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [msgs, busy]);

  const send = async () => {
    if ((!text.trim() && !attachment) || busy) return;
    setBusy(true);
    setNotice("");
    const userMsg: Msg = {
      role: "user",
      content: text || `[$attachment kind]`,
      attachments: attachment ? [{ name: attachment.file.name, kind: attachment.kind }] : undefined,
    };
    setMsgs((m) => [...m, userMsg]);
    try {
      let res: any;
      if (attachment) {
        const fd = new FormData();
        fd.append("payload", JSON.stringify({ user_id: user, session_id: session, text }));
        fd.append("files", attachment.file);
        const r = await fetch("/backend-api/chat/upload", { method: "POST", body: fd });
        if (!r.ok) throw new Error(await r.text());
        res = await r.json();
      } else {
        res = await post("/chat", { user_id: user, session_id: session, text });
      }
      setMsgs((m) => [
        ...m,
        {
          role: "assistant",
          content: res.answer,
          interactionId: res.interaction_id,
          confidence: res.confidence,
          verdict: res.verdict,
          flagged: res.flagged_for_review,
          sources: res.explanation?.sources,
          trace: res.explanation?.trace,
          model: res.model,
          topic: res.topic,
          suggestions: res.suggestions,
          guardFlagged: res.explanation?.trace?.some(
            (s: TraceStep) => s.step === "input_guard" && s.detail?.flagged,
          ),
        },
      ]);
    } catch (e: any) {
      // input guard (strict mode) blocks injections with 400 + detail.reasons
      let blocked = false;
      let reasons: string[] = [];
      const em = String(e.message || "");
      if (em.startsWith("400:")) {
        try {
          const d = JSON.parse(em.slice(4))?.detail;
          if (d?.blocked) {
            blocked = true;
            reasons = d.reasons || [];
          }
        } catch { /* not a guard block */ }
      }
      setMsgs((m) => [
        ...m,
        blocked
          ? { role: "assistant", content: "⛔ blocked by the input guard (strict mode).", blocked: true, blockReasons: reasons }
          : { role: "assistant", content: `⚠ error: ${e.message}` },
      ]);
    } finally {
      setText("");
      setAttachment(null);
      if (fileRef.current) fileRef.current.value = "";
      setBusy(false);
    }
  };

  const feedback = async (interactionId: number, kind: string, value?: any, fbText?: string) => {
    try {
      const res = await post("/chat/feedback", {
        interaction_id: interactionId, kind, value, text: fbText || "",
      });
      setMsgs((m) => m.map((x) => (x.interactionId === interactionId ? { ...x, reward: res.interaction_reward } : x)));
      setNotice(
        kind === "correction"
          ? `Correction learned (reward ${res.reward}). ${res.note || ""}`
          : `Feedback recorded — reward ${res.reward}. Policy: verbosity ${res.policy?.verbosity ?? "?"}.`,
      );
    } catch (e: any) {
      setNotice(`⚠ ${e.message}`);
    }
  };

  const pickFile = (f: File | undefined) => {
    if (!f) return;
    const kind = f.type.startsWith("image/") ? "image" : f.type.startsWith("audio/") ? "audio" : "text";
    const preview = kind === "image" ? URL.createObjectURL(f) : undefined;
    setAttachment({ file: f, kind, preview });
  };

  return (
    <>
      <div className="page-title">Chat</div>
      <div className="page-sub">
        multi-modal input (text · image · voice) · every answer is self-evaluated, cited and logged ·
        feedback tunes future answers for this user
      </div>

      <div className="row mb" style={{ gap: 12 }}>
        <div style={{ width: 170 }}>
          <label className="field">User (profile)</label>
          <select value={user} onChange={(e) => setUser(e.target.value)}>
            {USERS.map((u) => <option key={u}>{u}</option>)}
            <option value="guest">guest</option>
          </select>
        </div>
        <div style={{ width: 170 }}>
          <label className="field">Session</label>
          <input value={session} onChange={(e) => setSession(e.target.value)} />
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ alignSelf: "flex-end" }}>
          <button className="btn" onClick={() => setMsgs([])}>clear view</button>
        </div>
      </div>

      <Panel>
        <div className="chat-scroll" ref={scrollRef}>
          {msgs.length === 0 && (
            <div className="empty">
              Ask about the system itself — e.g. <i>“How does the reward model work?”</i> or{" "}
              <i>“What is drift detection?”</i> · upload an image or audio file · say{" "}
              <i>“remember that …”</i> to write long-term memory · ask something off-corpus to see
              the low-confidence path
            </div>
          )}
          {msgs.map((m, idx) => (
            <div key={idx} className={`msg ${m.role}`}>
              <div className="who">{m.role === "user" ? `${user} ▸` : "synapseos ▸"} {m.model ? <span className="faint">({m.model})</span> : null}</div>
              <div className="bubble">
                {m.attachments?.map((a, i) => (
                  <div key={i} className="badge b-purple" style={{ marginBottom: 6 }}>📎 {a.kind}: {a.name}</div>
                ))}
                {m.content}
                {m.blocked && m.blockReasons && m.blockReasons.length > 0 && (
                  <div className="mt">
                    {m.blockReasons.map((r, i) => (
                      <div key={i} className="mono-s faint">· {r}</div>
                    ))}
                  </div>
                )}
              </div>

              {m.role === "assistant" && m.interactionId && (
                <>
                  <div className="fb-row">
                    <button
                      className={`thumbs ${m.reward != null && m.reward > 0 ? "on-up" : ""}`}
                      title="thumbs up"
                      onClick={() => feedback(m.interactionId!, "thumb", "up")}
                    >
                      👍
                    </button>
                    <button
                      className={`thumbs ${m.reward != null && m.reward < 0 ? "on-down" : ""}`}
                      title="thumbs down"
                      onClick={() => feedback(m.interactionId!, "thumb", "down")}
                    >
                      👎
                    </button>
                    <select
                      style={{ width: 92, padding: "3px 6px", fontSize: 11 }}
                      defaultValue=""
                      onChange={(e) => e.target.value && feedback(m.interactionId!, "rating", Number(e.target.value))}
                    >
                      <option value="" disabled>★ rate</option>
                      {[5, 4, 3, 2, 1].map((r) => <option key={r} value={r}>{r} ★</option>)}
                    </select>
                    <button className="btn sm" onClick={() => { setCorrectionFor(m.interactionId!); setCorrectionText(""); }}>
                      ✎ correct
                    </button>
                    <Confidence value={m.confidence ?? 0} />
                    {m.flagged && <Badge tone="yellow">⚑ flagged for review</Badge>}
                    {m.guardFlagged && !m.blocked && <Badge tone="yellow">⛨ guard: flagged (monitor)</Badge>}
                    {m.reward != null && (
                      <Badge tone={m.reward >= 0 ? "green" : "red"}>reward {m.reward.toFixed(2)}</Badge>
                    )}
                    <button className="btn sm ghost" onClick={() => setOpenExplain(openExplain === idx ? null : idx)}>
                      {openExplain === idx ? "hide why ▴" : "why? ▾"}
                    </button>
                  </div>

                  {m.suggestions && m.suggestions.length > 0 && (
                    <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 4 }}>
                      <span className="small faint">next:</span>
                      {m.suggestions.map((s, i) => (
                        <button
                          key={i}
                          className="btn sm ghost"
                          title="ask this follow-up"
                          onClick={() => { setText(s); }}
                        >
                          {s}
                        </button>
                      ))}
                    </div>
                  )}

                  {correctionFor === m.interactionId && (
                    <div className="explain">
                      <div className="small dim mb">What should the answer have been? This is stored in long-term
                        memory and proposed as a learned fact for admin approval.</div>
                      <textarea
                        value={correctionText}
                        onChange={(e) => setCorrectionText(e.target.value)}
                        placeholder="e.g. The confidence threshold is 0.45, not 0.5"
                      />
                      <div className="row mt">
                        <button
                          className="btn primary sm"
                          disabled={!correctionText.trim()}
                          onClick={async () => {
                            await feedback(m.interactionId!, "correction", null, correctionText);
                            setCorrectionFor(null);
                          }}
                        >
                          submit correction
                        </button>
                        <button className="btn ghost sm" onClick={() => setCorrectionFor(null)}>cancel</button>
                      </div>
                    </div>
                  )}

                  {openExplain === idx && (
                    <div className="explain">
                      <div className="panel-title" style={{ marginBottom: 8 }}>Why this answer</div>
                      <div className="mb">
                        <div className="small dim">SOURCES ({m.sources?.length ?? 0})</div>
                        {m.sources?.map((s, i) => (
                          <div key={i} className="src">
                            <Badge tone={s.type === "fact" ? "cyan" : s.type === "memory" ? "purple" : "dim"}>{s.type}</Badge>
                            <div style={{ flex: 1 }}>
                              <div className="small">{s.title}</div>
                              <div className="mono-s faint">{s.snippet?.slice(0, 130)}…</div>
                            </div>
                            <span className="mono-s dim">{s.score?.toFixed(3)}</span>
                          </div>
                        ))}
                      </div>
                      <div className="small dim">REASONING TRACE</div>
                      {m.trace?.map((s, i) => (
                        <div key={i} className="trace-step">
                          <span className="dim">{i + 1}. {s.step.replace(/_/g, " ")}</span>
                          <div className="mono-s faint" style={{ whiteSpace: "pre-wrap", maxHeight: 110, overflow: "hidden" }}>
                            {JSON.stringify(s.detail).slice(0, 400)}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          ))}
          {busy && <div className="msg assistant"><div className="who">synapseos ▸</div><div className="bubble"><Spinner /> thinking — retrieving, generating, self-evaluating…</div></div>}
        </div>

        {notice && <div className="badge b-cyan mt" style={{ display: "block", padding: 8 }}>{notice}</div>}

        <hr className="sep" />
        {attachment && (
          <div className="row mb">
            <Badge tone="purple">📎 {attachment.kind}: {attachment.file.name}</Badge>
            {attachment.preview && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={attachment.preview} alt="attachment" style={{ height: 42, borderRadius: 6, border: "1px solid var(--border)" }} />
            )}
            <button className="btn sm ghost" onClick={() => { setAttachment(null); if (fileRef.current) fileRef.current.value = ""; }}>remove</button>
          </div>
        )}
        <div className="row" style={{ alignItems: "flex-end" }}>
          <div style={{ flex: 1 }}>
            <textarea
              style={{ minHeight: 54 }}
              value={text}
              placeholder="ask anything… (Enter to send, Shift+Enter for newline)"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
              }}
            />
          </div>
          <input ref={fileRef} type="file" accept="image/*,audio/*" style={{ display: "none" }} onChange={(e) => pickFile(e.target.files?.[0])} />
          <button className="btn" onClick={() => fileRef.current?.click()}>📎 attach</button>
          <button className="btn primary" onClick={send} disabled={busy || (!text.trim() && !attachment)}>send ▸</button>
        </div>
      </Panel>
    </>
  );
}
