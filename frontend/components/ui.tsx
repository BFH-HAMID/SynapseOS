"use client";

import React from "react";

export function Panel({
  title,
  children,
  right,
  style,
}: {
  title?: string;
  children: React.ReactNode;
  right?: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <section className="panel" style={style}>
      {(title || right) && (
        <div className="spread" style={{ marginBottom: 14 }}>
          {title && <div className="panel-title" style={{ marginBottom: 0 }}>{title}</div>}
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({
  num,
  lbl,
  sub,
  color,
}: {
  num: React.ReactNode;
  lbl: string;
  sub?: React.ReactNode;
  color?: string;
}) {
  return (
    <div className="stat">
      <div className="lbl">{lbl}</div>
      <div className="num" style={{ color: color || "var(--text)" }}>{num}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

export function Badge({ tone = "dim", children }: { tone?: string; children: React.ReactNode }) {
  return <span className={`badge b-${tone}`}>{children}</span>;
}

export function Confidence({ value }: { value: number }) {
  const color = value >= 0.6 ? "var(--green)" : value >= 0.45 ? "var(--yellow)" : "var(--red)";
  return (
    <span className="row" style={{ gap: 8, flex: 1, minWidth: 120 }}>
      <span className="conf-bar">
        <span className="conf-fill" style={{ width: `${Math.round(value * 100)}%`, background: color }} />
      </span>
      <span className="mono-s" style={{ color }}>{(value * 100).toFixed(0)}%</span>
    </span>
  );
}

export function Spinner() {
  return <span className="spinner" />;
}

export function Empty({ children = "nothing here yet" }: { children?: React.ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function ErrorBox({ error }: { error: string }) {
  return (
    <div className="badge b-red" style={{ whiteSpace: "pre-wrap", display: "block", padding: 10 }}>
      {error}
    </div>
  );
}
