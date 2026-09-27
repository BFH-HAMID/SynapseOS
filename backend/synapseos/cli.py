"""synapseos — command line tool.

  serve      run the API server
  chat       ask a question
  feedback   rate a past interaction
  ingest     add documents to the knowledge base
  facts      list / approve / reject learned facts
  kb         knowledge base versions + rollback
  stats      system statistics
  users      list users and profiles
  audit      security audit against a running instance (Parrot/Kali friendly)
  seed       seed demo data
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.parse

import httpx

from synapseos import __version__

C = {"red": "\033[91m", "yellow": "\033[93m", "green": "\033[92m",
     "cyan": "\033[96m", "dim": "\033[2m", "bold": "\033[1m", "end": "\033[0m"}


def c(txt: str, color: str) -> str:
    return f"{C[color]}{txt}{C['end']}"


class Client:
    def __init__(self, url: str, api_key: str | None, admin_key: str | None):
        self.base = url.rstrip("/")
        self.headers = {}
        if api_key:
            self.headers["X-API-Key"] = api_key
        self.admin_headers = dict(self.headers)
        if admin_key:
            self.admin_headers["X-API-Key"] = admin_key

    def get(self, path, **kw):
        return httpx.get(f"{self.base}/api/v1{path}", headers=self.headers, timeout=60, **kw)

    def post(self, path, body=None, admin=False, **kw):
        return httpx.post(f"{self.base}/api/v1{path}",
                          headers=self.admin_headers if admin else self.headers,
                          json=body, timeout=120, **kw)

    def delete(self, path):
        return httpx.delete(f"{self.base}/api/v1{path}", headers=self.admin_headers, timeout=60)


def cmd_serve(args) -> int:
    import uvicorn

    print(c(f"◉ SynapseOS v{__version__} — starting API server on {args.host}:{args.port}", "cyan"))
    uvicorn.run("synapseos.main:app", host=args.host, port=args.port,
                reload=args.reload, log_level=args.log_level)
    return 0


def cmd_chat(args) -> int:
    client = Client(args.url, args.api_key, args.admin_key)
    attachments = []
    if args.image:
        with open(args.image, "rb") as f:
            attachments.append({"kind": "image", "filename": args.image,
                                "data_base64": base64.b64encode(f.read()).decode()})
    if args.audio:
        with open(args.audio, "rb") as f:
            attachments.append({"kind": "audio", "filename": args.audio,
                                "transcript": args.transcript or "",
                                "data_base64": base64.b64encode(f.read()).decode()})
    r = client.post("/chat", {"user_id": args.user, "session_id": args.session,
                              "text": args.text, "attachments": attachments})
    if r.status_code != 200:
        print(c(f"error {r.status_code}: {r.text}", "red"))
        return 1
    d = r.json()
    print(d["answer"])
    conf = d.get("confidence", 0)
    col = "green" if conf >= 0.45 else "yellow"
    print(c(f"\n  confidence {conf:.2f} · topic {d.get('topic')} · model {d.get('model')} "
            f"· interaction #{d['interaction_id']}", "dim"))
    srcs = d.get("explanation", {}).get("sources", [])
    if srcs:
        print(c("  sources:", "dim"))
        for s in srcs[:5]:
            print(c(f"   [{s['type']}] {s['title'][:60]} (score {s.get('score', 0):.2f})", "dim"))
    if d.get("flagged_for_review"):
        print(c("  ⚑ flagged for human review (low confidence)", "yellow"))
    return 0


def cmd_feedback(args) -> int:
    client = Client(args.url, args.api_key, args.admin_key)
    body = {"interaction_id": args.interaction_id, "kind": args.kind}
    if args.kind == "thumb":
        body["value"] = args.thumb
    if args.kind == "rating":
        body["value"] = args.rating
    if args.text:
        body["text"] = args.text
    r = client.post("/chat/feedback", body)
    print(json.dumps(r.json(), indent=2) if r.status_code == 200
          else c(f"error {r.status_code}: {r.text}", "red"))
    return 0 if r.status_code == 200 else 1


def cmd_ingest(args) -> int:
    client = Client(args.url, args.api_key, args.admin_key)
    ok = 0
    for path in args.files:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            print(c(f"  ✗ {path}: {e}", "red"))
            continue
        title = args.title or path.rsplit("/", 1)[-1]
        r = client.post("/documents", {"title": title, "text": text, "source": path})
        if r.status_code == 200:
            print(c(f"  ✓ {title} → document #{r.json()['id']}", "green"))
            ok += 1
        else:
            print(c(f"  ✗ {path}: {r.text}", "red"))
    return 0 if ok else 1


def cmd_facts(args) -> int:
    client = Client(args.url, args.api_key, args.admin_key)
    if args.action == "list":
        r = client.get(f"/kb/facts?status={args.status}" if args.status != "all" else "/kb/facts")
        for f in r.json():
            mark = {"active": "●", "pending": "◌", "rejected": "✗", "retired": "○"}.get(f["status"], "?")
            col = "green" if f["status"] == "active" else "yellow" if f["status"] == "pending" else "dim"
            print(c(f"  {mark} #{f['id']:<4} [{f['status']:<8}] {f['statement'][:90]}", col))
        return 0
    if args.action == "approve":
        r = client.post(f"/kb/facts/{args.id}/approve", {}, admin=True)
    elif args.action == "reject":
        r = client.post(f"/kb/facts/{args.id}/reject", {}, admin=True)
    elif args.action == "propose":
        r = client.post("/kb/facts", {"statement": args.statement, "auto_active": args.active})
    else:
        print(c("unknown action", "red"))
        return 1
    print(json.dumps(r.json(), indent=2) if r.status_code == 200
          else c(f"error {r.status_code}: {r.text}", "red"))
    return 0 if r.status_code == 200 else 1


def cmd_kb(args) -> int:
    client = Client(args.url, args.api_key, args.admin_key)
    if args.action == "versions":
        r = client.get("/kb/versions")
        for v in r.json():
            print(c(f"  v{v['id']:<4} {v['label'][:70]}", "cyan") +
                  c(f"   facts:{v['facts']} docs:{v['documents']} {v['created_at'][:19]}", "dim"))
        return 0
    if args.action == "rollback":
        r = client.post(f"/kb/versions/{args.version}/rollback", {}, admin=True)
        print(json.dumps(r.json(), indent=2) if r.status_code == 200
              else c(f"error {r.status_code}: {r.text}", "red"))
        return 0 if r.status_code == 200 else 1
    if args.action == "resync":
        r = client.post("/kb/resync", {}, admin=True)
        print(json.dumps(r.json(), indent=2))
        return 0
    print(c("unknown action", "red"))
    return 1


def cmd_stats(args) -> int:
    client = Client(args.url, args.api_key, args.admin_key)
    r = client.get("/admin/overview")
    if r.status_code != 200:
        print(c(f"error {r.status_code}: {r.text}", "red"))
        return 1
    d = r.json()
    t, a = d["totals"], d["averages"]
    print(c(f"◉ SynapseOS — {args.url}", "cyan"))
    print(f"  interactions   {t['interactions']:<8} feedback      {t['feedback']}")
    print(f"  users          {t['users']:<8} documents     {t['documents']}")
    print(f"  facts active   {t['facts_active']:<8} facts pending {t['facts_pending']}")
    print(f"  flagged        {t['flagged']:<8} open reviews  {t['open_reviews']}")
    print(f"  drift events   {t['drift_events']}")
    print(f"  avg reward     {a['reward']:<8} avg confidence {a['confidence']}")
    print(f"  avg latency    {a['latency_ms']}ms")
    rm = d.get("reward_model", {})
    print(c(f"  reward EMAs: {json.dumps(rm.get('emas', {}))}", "dim"))
    print(c(f"  vectors: {json.dumps(d.get('vector_store', {}))}", "dim"))
    return 0


def cmd_users(args) -> int:
    client = Client(args.url, args.api_key, args.admin_key)
    if args.user:
        r = client.get(f"/users/{urllib.parse.quote(args.user)}/profile")
        print(json.dumps(r.json(), indent=2) if r.status_code == 200
              else c(f"error {r.status_code}: {r.text}", "red"))
        return 0 if r.status_code == 200 else 1
    for u in client.get("/users").json():
        print(c(f"  ● {u['ext_id']:<12} {u['name']:<12}", "cyan") +
              c(f"interactions:{u['interactions']} "
                f"topics:{list((u['profile'].get('topic_affinity') or {}).keys())}", "dim"))
    return 0


def cmd_audit(args) -> int:
    from synapseos.security.audit import run_audit

    report = run_audit(args.url, timeout=args.timeout, out_path=args.out)
    report.print()
    print(c(f"  report written to {args.out}", "dim"))
    return 1 if report.high_count > 0 else 0


def cmd_seed(args) -> int:
    from synapseos.core.config import get_settings
    from synapseos.engine import build_engine
    from synapseos.seed import seed

    print(c("◉ Seeding SynapseOS demo data…", "cyan"))
    if args.reset:
        print(c("  (reset: wiping existing data)", "yellow"))
    settings = get_settings()
    engine = build_engine(settings)
    result = seed(engine, settings, reset=args.reset)
    print(c(f"◉ done: {json.dumps(result)}", "green"))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="synapseos",
                                description="SynapseOS — self-learning AI system CLI")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--url", default="http://127.0.0.1:8000", help="API base URL")
    common.add_argument("--api-key", default=None, help="API key (or SYNAPSE_API_KEYS env)")
    common.add_argument("--admin-key", default=None, help="admin key (or SYNAPSE_ADMIN_KEY env)")
    p.add_argument("--version", action="version", version=f"synapseos {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the API server", parents=[common])
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")
    s.add_argument("--log-level", default="info")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("chat", help="ask a question", parents=[common])
    s.add_argument("text")
    s.add_argument("--user", default="cli-user")
    s.add_argument("--session", default="cli")
    s.add_argument("--image", help="path to image attachment")
    s.add_argument("--audio", help="path to audio attachment")
    s.add_argument("--transcript", default="", help="transcript text for the audio clip")
    s.set_defaults(fn=cmd_chat)

    s = sub.add_parser("feedback", help="rate an interaction", parents=[common])
    s.add_argument("interaction_id", type=int)
    s.add_argument("--kind", choices=["thumb", "rating", "correction", "text"], required=True)
    s.add_argument("--thumb", choices=["up", "down"])
    s.add_argument("--rating", type=float)
    s.add_argument("--text", default="")
    s.set_defaults(fn=cmd_feedback)

    s = sub.add_parser("ingest", help="ingest documents (txt/md)", parents=[common])
    s.add_argument("files", nargs="+")
    s.add_argument("--title", default=None)
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("facts", help="manage learned facts", parents=[common])
    s.add_argument("action", choices=["list", "approve", "reject", "propose"])
    s.add_argument("--status", default="pending")
    s.add_argument("--id", type=int)
    s.add_argument("--statement", default=None)
    s.add_argument("--active", action="store_true", help="propose + approve immediately")
    s.set_defaults(fn=cmd_facts)

    s = sub.add_parser("kb", help="knowledge base versions", parents=[common])
    s.add_argument("action", choices=["versions", "rollback", "resync"])
    s.add_argument("--version", type=int)
    s.set_defaults(fn=cmd_kb)

    s = sub.add_parser("stats", help="system statistics", parents=[common])
    s.set_defaults(fn=cmd_stats)

    s = sub.add_parser("users", help="list users / show profile", parents=[common])
    s.add_argument("user", nargs="?")
    s.set_defaults(fn=cmd_users)

    s = sub.add_parser("audit", help="security audit against a running instance", parents=[common])
    s.add_argument("--timeout", type=float, default=10.0)
    s.add_argument("--out", default="audit-report.json")
    s.set_defaults(fn=cmd_audit)

    s = sub.add_parser("seed", help="seed demo data (docs, interactions, feedback)", parents=[common])
    s.add_argument("--reset", action="store_true", help="wipe data before seeding")
    s.set_defaults(fn=cmd_seed)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
