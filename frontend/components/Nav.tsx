"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const LINKS = [
  { href: "/", label: "Overview", icon: "◉" },
  { href: "/chat", label: "Chat", icon: "❯" },
  { href: "/review", label: "Review Queue", icon: "⚑", badge: "review" },
  { href: "/knowledge", label: "Knowledge Base", icon: "▣" },
  { href: "/metrics", label: "Learning Metrics", icon: "∿" },
  { href: "/drift", label: "Drift & Anomalies", icon: "◈", badge: "drift" },
  { href: "/users", label: "Users & Profiles", icon: "◇" },
];

export default function Nav() {
  const path = usePathname();
  const [counts, setCounts] = useState<{ review?: number; drift?: number }>({});

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const overview = await fetch("/backend-api/admin/overview").then((r) => r.json());
        if (alive)
          setCounts({
            review: overview?.totals?.open_reviews,
            drift: overview?.totals?.drift_events,
          });
      } catch {
        /* backend may be restarting */
      }
    };
    load();
    const t = setInterval(load, 15000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  return (
    <aside className="sidebar">
      <div className="logo">
        SYNAPSE<span className="pulse">OS</span>
      </div>
      <div className="logo-sub">self-learning AI system</div>
      <nav>
        {LINKS.map((l) => {
          const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
          const n = l.badge === "review" ? counts.review : l.badge === "drift" ? counts.drift : null;
          return (
            <Link key={l.href} href={l.href} className={`nav-link ${active ? "active" : ""}`}>
              <span style={{ opacity: 0.7 }}>{l.icon}</span> {l.label}
              {!!n && (
                <span className="nav-badge badge b-yellow">{n}</span>
              )}
            </Link>
          );
        })}
      </nav>
      <div style={{ marginTop: 30, fontSize: 11, color: "var(--text-faint)" }}>
        <div style={{ marginBottom: 6 }}>─ engine ─</div>
        <a href="/backend-api/health" target="_blank" style={{ color: "var(--text-faint)" }}>
          /api/v1/health ↗
        </a>
        <br />
        <a href="/docs-link" target="_blank" style={{ color: "var(--text-faint)", pointerEvents: "none", opacity: 0.5 }}>
          OpenAPI: :8000/docs
        </a>
      </div>
    </aside>
  );
}
