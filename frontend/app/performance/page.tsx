"use client";

import { useState, useEffect } from "react";
import Link from "next/link";

interface TierStats {
  signals: number;
  win_rate: number | null;
  avg_clv_pp: number | null;
}

interface RecentSignal {
  match: string;
  kickoff: string | null;
  signal_outcome: string;
  actual_result: string;
  hit: boolean;
  signal_source: "edge" | "fuerza" | null;
  lineup_confirmed: boolean | null;
  model_prob: number | null;
  entry_poly_prob: number | null;
  closing_poly_prob: number | null;
  clv_pp: number | null;
  resolved_at: string;
}

interface PerformanceData {
  total_signals: number;
  win_rate: number | null;
  avg_clv_pp: number | null;
  brier_model: number | null;
  brier_market: number | null;
  roi_simulation: number | null;
  by_source: { edge: TierStats; fuerza: TierStats };
  recent: RecentSignal[];
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";
const mono: React.CSSProperties = { fontFamily: "var(--mono, monospace)" };

function StatCard({
  label,
  value,
  sub,
  color,
  tooltip,
}: {
  label: string;
  value: string;
  sub?: string;
  color?: string;
  tooltip?: string;
}) {
  return (
    <div
      title={tooltip}
      style={{
        border: "1px solid var(--border, #e5e7eb)",
        borderRadius: 8,
        padding: "14px 16px",
        background: "var(--surface, #fff)",
        flex: 1,
        minWidth: 140,
      }}
    >
      <p
        style={{
          fontSize: 10,
          color: "var(--muted, #888)",
          textTransform: "uppercase",
          letterSpacing: "0.1em",
          marginBottom: 6,
          ...mono,
        }}
      >
        {label}
      </p>
      <p
        style={{
          fontSize: 22,
          fontWeight: 600,
          color: color ?? "var(--text, #111)",
          ...mono,
        }}
      >
        {value}
      </p>
      {sub && (
        <p style={{ fontSize: 11, color: "var(--muted, #888)", marginTop: 4 }}>
          {sub}
        </p>
      )}
    </div>
  );
}

function outcomeLabel(o: string) {
  return o === "home" ? "Local" : o === "away" ? "Visit." : "Empate";
}

function pct(v: number | null, decimals = 1) {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(decimals)}%`;
}

function pp(v: number | null) {
  if (v === null || v === undefined) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}pp`;
}

export default function PerformancePage() {
  const [data, setData] = useState<PerformanceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/performance`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div style={{ maxWidth: 860, margin: "0 auto", padding: "40px 20px", textAlign: "center" }}>
        <p style={{ color: "var(--muted, #888)", fontSize: 13, ...mono }}>Cargando datos de performance…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ maxWidth: 860, margin: "0 auto", padding: "40px 20px", textAlign: "center" }}>
        <p style={{ color: "var(--red, #dc2626)", fontSize: 13, ...mono }}>Error: {error}</p>
      </div>
    );
  }

  const d = data!;
  const noData = d.total_signals === 0;

  // CLV color
  const clvColor =
    d.avg_clv_pp === null
      ? "var(--muted, #888)"
      : d.avg_clv_pp > 0
      ? "var(--green, #16a34a)"
      : "var(--red, #dc2626)";

  // Brier comparison
  const brierBetter =
    d.brier_model !== null &&
    d.brier_market !== null &&
    d.brier_model < d.brier_market;

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "24px 20px 80px" }}>
      {/* Nav */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 28 }}>
        <Link
          href="/"
          style={{ fontSize: 12, color: "var(--muted, #888)", textDecoration: "none", ...mono }}
        >
          ← Inicio
        </Link>
        <h1 style={{ fontSize: 18, fontWeight: 600, color: "var(--text, #111)" }}>
          Performance del modelo
        </h1>
        <span
          style={{
            fontSize: 10,
            color: "var(--muted, #888)",
            background: "var(--bg, #f9fafb)",
            border: "1px solid var(--border, #e5e7eb)",
            borderRadius: 4,
            padding: "2px 6px",
            ...mono,
          }}
        >
          PRIVADO
        </span>
      </div>

      {noData ? (
        <div
          style={{
            border: "1px solid var(--border, #e5e7eb)",
            borderRadius: 8,
            padding: "40px 24px",
            textAlign: "center",
            background: "var(--surface, #fff)",
          }}
        >
          <p style={{ fontSize: 14, color: "var(--text, #111)", marginBottom: 8 }}>
            Sin señales resueltas todavía
          </p>
          <p style={{ fontSize: 12, color: "var(--muted, #888)" }}>
            Los datos aparecerán automáticamente cuando los partidos con señal Edge/Fuerza
            terminen. El sistema revisa resultados cada hora.
          </p>
        </div>
      ) : (
        <>
          {/* Main stats row */}
          <div
            style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 16 }}
          >
            <StatCard
              label="Señales resueltas"
              value={String(d.total_signals)}
              sub="partidos analizados"
              tooltip="Total de señales Edge o Fuerza emitidas y con resultado conocido"
            />
            <StatCard
              label="Win rate"
              value={pct(d.win_rate)}
              sub={`${Math.round((d.win_rate ?? 0) * (d.total_signals ?? 0))} de ${d.total_signals ?? 0} aciertos`}
              color={
                d.win_rate === null
                  ? "var(--muted)"
                  : d.win_rate >= 0.5
                  ? "var(--green, #16a34a)"
                  : "var(--red, #dc2626)"
              }
              tooltip="Porcentaje de señales donde el outcome predicho fue correcto"
            />
            <StatCard
              label="Market Drift"
              value={pp(d.avg_clv_pp)}
              sub="cierre vs entrada (pp)"
              color={clvColor}
              tooltip="Market Drift: ¿se movieron las odds de Polymarket hacia nuestra predicción antes del partido? Positivo = el mercado confirmó nuestra señal. (Métrica propia, ≠ CLV estándar)"
            />
            <StatCard
              label="ROI simulado"
              value={
                d.roi_simulation === null
                  ? "—"
                  : `${d.roi_simulation >= 0 ? "+" : ""}${d.roi_simulation.toFixed(1)}%`
              }
              color={
                d.roi_simulation === null
                  ? "var(--muted)"
                  : d.roi_simulation >= 0
                  ? "var(--green, #16a34a)"
                  : "var(--red, #dc2626)"
              }
              tooltip="Simulación apostando 1 unidad plana en cada señal a las odds de entrada"
            />
          </div>

          {/* Brier Score comparison */}
          <div
            style={{
              border: "1px solid var(--border, #e5e7eb)",
              borderRadius: 8,
              padding: "14px 16px",
              background: "var(--surface, #fff)",
              marginBottom: 16,
            }}
          >
            <p
              style={{
                fontSize: 10,
                color: "var(--muted, #888)",
                textTransform: "uppercase",
                letterSpacing: "0.1em",
                marginBottom: 12,
                ...mono,
              }}
            >
              Brier Score — Modelo vs Polymarket
            </p>
            <div style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "center" }}>
              <div>
                <p style={{ fontSize: 10, color: "var(--muted, #888)", marginBottom: 4 }}>
                  Dixon-Coles
                </p>
                <p
                  style={{
                    fontSize: 20,
                    fontWeight: 600,
                    color: brierBetter ? "var(--green, #16a34a)" : "var(--text, #111)",
                    ...mono,
                  }}
                >
                  {d.brier_model?.toFixed(4) ?? "—"}
                </p>
              </div>
              <div style={{ fontSize: 18, color: "var(--muted, #888)" }}>vs</div>
              <div>
                <p style={{ fontSize: 10, color: "var(--muted, #888)", marginBottom: 4 }}>
                  Polymarket (precio entrada)
                </p>
                <p
                  style={{
                    fontSize: 20,
                    fontWeight: 600,
                    color: brierBetter ? "var(--muted, #888)" : "var(--green, #16a34a)",
                    ...mono,
                  }}
                >
                  {d.brier_market?.toFixed(4) ?? "—"}
                </p>
              </div>
              {d.brier_model !== null && d.brier_market !== null && (
                <div
                  style={{
                    marginLeft: "auto",
                    fontSize: 12,
                    color: brierBetter ? "var(--green, #16a34a)" : "var(--red, #dc2626)",
                    fontWeight: 500,
                  }}
                >
                  {brierBetter
                    ? "Modelo supera al mercado"
                    : "Mercado supera al modelo"}
                  <span style={{ color: "var(--muted, #888)", fontWeight: 400 }}>
                    {" "}(0 = perfecto, 0.25 = azar)
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* By signal source */}
          <div
            style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 16 }}
          >
            {(["edge", "fuerza"] as const).map((source) => {
              const t = d.by_source[source];
              return (
                <div
                  key={source}
                  style={{
                    border: "1px solid var(--border, #e5e7eb)",
                    borderRadius: 8,
                    padding: "14px 16px",
                    background: "var(--surface, #fff)",
                    flex: 1,
                    minWidth: 200,
                  }}
                >
                  <p
                    style={{
                      fontSize: 10,
                      color: source === "edge" ? "var(--green, #16a34a)" : "var(--amber, #d97706)",
                      textTransform: "uppercase",
                      letterSpacing: "0.1em",
                      marginBottom: 10,
                      fontWeight: 600,
                      ...mono,
                    }}
                  >
                    {source === "edge" ? "⚡ Edge confirmado" : "💪 Apuesta de fuerza"}
                  </p>
                  <div style={{ display: "flex", gap: 20 }}>
                    <div>
                      <p style={{ fontSize: 10, color: "var(--muted, #888)" }}>Señales</p>
                      <p style={{ fontSize: 18, fontWeight: 600, ...mono }}>{t.signals}</p>
                    </div>
                    <div>
                      <p style={{ fontSize: 10, color: "var(--muted, #888)" }}>Win rate</p>
                      <p style={{ fontSize: 18, fontWeight: 600, ...mono }}>
                        {pct(t.win_rate)}
                      </p>
                    </div>
                    <div>
                      <p style={{ fontSize: 10, color: "var(--muted, #888)" }}>CLV</p>
                      <p
                        style={{
                          fontSize: 18,
                          fontWeight: 600,
                          ...mono,
                          color:
                            t.avg_clv_pp === null
                              ? "var(--muted)"
                              : t.avg_clv_pp > 0
                              ? "var(--green, #16a34a)"
                              : "var(--red, #dc2626)",
                        }}
                      >
                        {pp(t.avg_clv_pp)}
                      </p>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Recent signals table */}
          <div
            style={{
              border: "1px solid var(--border, #e5e7eb)",
              borderRadius: 8,
              background: "var(--surface, #fff)",
              overflow: "hidden",
            }}
          >
            <p
              style={{
                fontSize: 10,
                color: "var(--muted, #888)",
                textTransform: "uppercase",
                letterSpacing: "0.1em",
                padding: "12px 16px",
                borderBottom: "1px solid var(--border, #e5e7eb)",
                ...mono,
              }}
            >
              Últimas señales · {d.recent.length} de {d.total_signals}
            </p>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ background: "var(--bg, #f9fafb)" }}>
                    {[
                      "Partido",
                      "Señal",
                      "Resultado",
                      "Acierto",
                      "Modelo",
                      "Entrada",
                      "Cierre",
                      "Drift",
                    ].map((h) => (
                      <th
                        key={h}
                        style={{
                          padding: "8px 12px",
                          textAlign: "left",
                          fontSize: 10,
                          color: "var(--muted, #888)",
                          fontWeight: 500,
                          whiteSpace: "nowrap",
                          ...mono,
                        }}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {d.recent.map((s, i) => (
                    <tr
                      key={i}
                      style={{ borderTop: "1px solid var(--border, #e5e7eb)" }}
                    >
                      <td
                        style={{
                          padding: "8px 12px",
                          color: "var(--text, #111)",
                          maxWidth: 200,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {s.match}
                      </td>
                      <td style={{ padding: "8px 12px", whiteSpace: "nowrap" }}>
                        <span
                          style={{
                            ...mono,
                            fontSize: 10,
                            background:
                              s.signal_source === "edge" ? "#f0fdf4" : "#fffbeb",
                            color:
                              s.signal_source === "edge"
                                ? "var(--green, #16a34a)"
                                : "var(--amber, #d97706)",
                            padding: "2px 6px",
                            borderRadius: 4,
                            marginRight: 6,
                          }}
                        >
                          {s.signal_source === "edge" ? "⚡ EDGE" : s.signal_source === "fuerza" ? "💪 FUERZA" : "?"}
                        </span>
                        {outcomeLabel(s.signal_outcome)}
                      </td>
                      <td
                        style={{
                          padding: "8px 12px",
                          color: "var(--muted, #888)",
                          ...mono,
                        }}
                      >
                        {outcomeLabel(s.actual_result)}
                      </td>
                      <td style={{ padding: "8px 12px" }}>
                        <span
                          style={{
                            fontSize: 14,
                            color: s.hit ? "var(--green, #16a34a)" : "var(--red, #dc2626)",
                          }}
                        >
                          {s.hit ? "✓" : "✗"}
                        </span>
                      </td>
                      <td
                        style={{ padding: "8px 12px", color: "var(--muted, #888)", ...mono }}
                      >
                        {pct(s.model_prob, 0)}
                      </td>
                      <td
                        style={{ padding: "8px 12px", color: "var(--muted, #888)", ...mono }}
                      >
                        {pct(s.entry_poly_prob, 0)}
                      </td>
                      <td
                        style={{ padding: "8px 12px", color: "var(--muted, #888)", ...mono }}
                      >
                        {pct(s.closing_poly_prob, 0)}
                      </td>
                      <td
                        style={{
                          padding: "8px 12px",
                          fontWeight: 500,
                          ...mono,
                          color:
                            s.clv_pp === null
                              ? "var(--muted, #888)"
                              : s.clv_pp > 0
                              ? "var(--green, #16a34a)"
                              : "var(--red, #dc2626)",
                        }}
                      >
                        {pp(s.clv_pp)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
