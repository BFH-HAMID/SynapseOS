"use client";

import React from "react";

// Dependency-free SVG charts.

export function LineChart({
  series,
  height = 180,
  yMin,
  yMax,
  yLabel,
}: {
  series: { name: string; color: string; points: { x: string; y: number | null }[]; dashed?: boolean }[];
  height?: number;
  yMin?: number;
  yMax?: number;
  yLabel?: string;
}) {
  const W = 720;
  const H = height;
  const pad = { l: 34, r: 10, t: 12, b: 22 };
  const all = series.flatMap((s) => s.points.map((p) => p.y).filter((y): y is number => y !== null));
  if (!all.length) return <div className="empty">no data</div>;
  const lo = yMin ?? Math.min(...all);
  const hi = yMax ?? Math.max(...all);
  const span = hi - lo || 1;
  const n = Math.max(...series.map((s) => s.points.length));
  const x = (i: number) => pad.l + (i / Math.max(n - 1, 1)) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - (v - lo) / span) * (H - pad.t - pad.b);
  const ticks = [lo, lo + span / 2, hi];

  return (
    <div style={{ overflowX: "auto" }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", minWidth: 420 }}>
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke="var(--border-soft)" strokeDasharray="3 4" />
            <text x={4} y={y(t) + 3} fill="var(--text-faint)" fontSize="9">
              {Math.abs(t) >= 100 ? t.toFixed(0) : t.toFixed(2)}
            </text>
          </g>
        ))}
        {series.map((s) => {
          const pts = s.points
            .map((p, i) => (p.y === null ? null : `${x(i)},${y(p.y)}`))
            .filter(Boolean)
            .join(" ");
          return (
            <polyline
              key={s.name}
              points={pts}
              fill="none"
              stroke={s.color}
              strokeWidth="2"
              strokeDasharray={s.dashed ? "5 4" : undefined}
              strokeLinejoin="round"
            />
          );
        })}
        {series[0].points.map((p, i) =>
          i % Math.ceil(n / 8) === 0 ? (
            <text key={i} x={x(i)} y={H - 6} fill="var(--text-faint)" fontSize="8.5" textAnchor="middle">
              {p.x.slice(5)}
            </text>
          ) : null
        )}
        {yLabel && (
          <text x={pad.l} y={10} fill="var(--text-faint)" fontSize="9">
            {yLabel}
          </text>
        )}
      </svg>
      <div className="row" style={{ gap: 16, marginTop: 4 }}>
        {series.map((s) => (
          <span key={s.name} className="row" style={{ gap: 6 }}>
            <span style={{ width: 14, height: 2, background: s.color, borderRadius: 2, display: "inline-block" }} />
            <span className="mono-s dim">{s.name}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

export function BarRow({
  label,
  value,
  max,
  color = "var(--cyan)",
  right,
}: {
  label: React.ReactNode;
  value: number;
  max: number;
  color?: string;
  right?: React.ReactNode;
}) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="row" style={{ gap: 10, marginBottom: 7 }}>
      <span style={{ width: 150, fontSize: 12.5 }} className="dim">{label}</span>
      <span style={{ flex: 1, height: 14, background: "var(--bg-soft)", borderRadius: 4, border: "1px solid var(--border-soft)", overflow: "hidden" }}>
        <span style={{ display: "block", height: "100%", width: `${pct}%`, background: color, opacity: 0.75 }} />
      </span>
      <span className="mono-s" style={{ width: 70, textAlign: "right" }}>{right ?? value}</span>
    </div>
  );
}
