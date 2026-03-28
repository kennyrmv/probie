"use client";

import { useState } from "react";

interface MissingPlayer {
  name: string;
  reason: string;
}

interface TopPlayer {
  name: string;
  position: string;
  impact: string;
  form: string;
}

interface BetSignal {
  type: "value" | "favorite" | "none";
  side: "home" | "draw" | "away" | null;
  confidence: "alta" | "media" | "baja";
  reasoning: string;
}

interface ProbAdjustment {
  home: number;
  draw: number;
  away: number;
  reasoning: string;
}

export interface AnalysisData {
  source: string;
  analyzed_at: string;
  home_lineup: string[];
  away_lineup: string[];
  home_missing: MissingPlayer[];
  away_missing: MissingPlayer[];
  top_players_home: TopPlayer[];
  top_players_away: TopPlayer[];
  form_home: string;
  form_away: string;
  context: string;
  key_factors: string[];
  prob_adjustment: ProbAdjustment | null;
  bet_signal: BetSignal | null;
  lineup_confirmed: boolean;
  confidence: "alta" | "media" | "baja";
  sources: string[];
}

function timeAgo(iso: string): string {
  try {
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 60) return "justo ahora";
    if (diff < 3600) return `hace ${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `hace ${Math.floor(diff / 3600)}h`;
    return `hace ${Math.floor(diff / 86400)}d`;
  } catch {
    return "";
  }
}

const CONFIDENCE_COLOR: Record<string, string> = {
  alta: "var(--green)",
  media: "var(--amber)",
  baja: "var(--muted)",
};

const SIGNAL_CONFIG = {
  value: { label: "EDGE REAL", color: "var(--green)", bg: "#f0fdf4", border: "var(--green)" },
  favorite: { label: "FAVORITO VÁLIDO", color: "var(--amber)", bg: "#fffbeb", border: "var(--amber)" },
  none: { label: "SIN SEÑAL", color: "var(--muted)", bg: "var(--surface)", border: "var(--border)" },
};

function TopPlayerCard({ player }: { player: TopPlayer }) {
  return (
    <div style={{
      padding: "7px 10px",
      background: "var(--bg)",
      border: "1px solid var(--border)",
      borderRadius: 6,
      flex: 1,
      minWidth: 0,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 3 }}>
        <span className="mono" style={{ fontSize: 9, color: "var(--muted)", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 3, padding: "1px 4px" }}>
          {player.position}
        </span>
        <span style={{ fontSize: 11, fontWeight: 600, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {player.name}
        </span>
      </div>
      <p style={{ fontSize: 10, color: "var(--text)", lineHeight: 1.5, margin: 0 }}>{player.impact}</p>
      {player.form && (
        <p className="mono" style={{ fontSize: 9, color: "var(--muted)", marginTop: 3, margin: "3px 0 0" }}>{player.form}</p>
      )}
    </div>
  );
}

export default function AnalysisPanel({
  matchId,
  homeTeam,
  awayTeam,
  initialData,
}: {
  matchId: string;
  homeTeam: string;
  awayTeam: string;
  initialData: AnalysisData | null;
}) {
  const [data, setData] = useState<AnalysisData | null>(initialData);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/matches/${matchId}/analyze`, {
        method: "POST",
      });
      // Guard against non-JSON error pages (Starlette HTML 500s)
      const ct = res.headers.get("content-type") ?? "";
      if (!ct.includes("application/json")) {
        throw new Error(`Error del servidor (HTTP ${res.status})`);
      }
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`);
      setData(json.analysis);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error desconocido");
    } finally {
      setLoading(false);
    }
  };

  // ── Idle state ────────────────────────────────────────────────────────────
  if (!data && !loading && !error) {
    return (
      <div style={{ padding: "10px 16px 12px", borderTop: "1px solid var(--border)" }}>
        <button
          onClick={run}
          style={{
            fontSize: 11,
            fontFamily: "var(--mono)",
            color: "var(--text)",
            background: "var(--bg)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            padding: "5px 12px",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <span>🔍</span> Analizar partido
        </button>
      </div>
    );
  }

  // ── Loading ───────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div style={{ padding: "10px 16px 12px", borderTop: "1px solid var(--border)" }}>
        <span className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>
          ⏳ Buscando en internet y analizando con IA…
        </span>
      </div>
    );
  }

  // ── Error ─────────────────────────────────────────────────────────────────
  if (error) {
    return (
      <div style={{ padding: "10px 16px 12px", borderTop: "1px solid var(--border)", display: "flex", gap: 12, alignItems: "center" }}>
        <span className="mono" style={{ fontSize: 11, color: "var(--red, #dc2626)" }}>✕ {error}</span>
        <button onClick={run} style={{ fontSize: 11, color: "var(--muted)", background: "none", border: "none", cursor: "pointer", textDecoration: "underline", fontFamily: "var(--mono)" }}>
          reintentar
        </button>
      </div>
    );
  }

  if (!data) return null;

  // ── Analysis panel ────────────────────────────────────────────────────────
  const allMissing = [
    ...(data.home_missing || []).map(p => ({ ...p, team: homeTeam })),
    ...(data.away_missing || []).map(p => ({ ...p, team: awayTeam })),
  ];
  const confidenceColor = CONFIDENCE_COLOR[data.confidence] || "var(--muted)";
  const signal = data.bet_signal;
  const signalCfg = signal ? SIGNAL_CONFIG[signal.type] : null;

  return (
    <div style={{ borderTop: "1px solid var(--border)" }}>

      {/* Header row */}
      <div style={{ padding: "8px 16px 0", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span className="mono" style={{ fontSize: 9, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.1em" }}>
          Análisis IA · {timeAgo(data.analyzed_at)}
          {" · "}
          <span style={{ color: confidenceColor }}>confianza {data.confidence}</span>
        </span>
        <button
          onClick={run}
          disabled={loading}
          style={{ fontSize: 10, color: "var(--muted)", background: "none", border: "none", cursor: "pointer", fontFamily: "var(--mono)" }}
        >
          ↺ re-analizar
        </button>
      </div>

      <div style={{ padding: "8px 16px 14px", display: "flex", flexDirection: "column", gap: 10 }}>

        {/* ── BET SIGNAL — la señal principal ── */}
        {signal && signalCfg && signal.type !== "none" && (
          <div style={{
            padding: "10px 12px",
            background: signalCfg.bg,
            border: `1px solid ${signalCfg.border}`,
            borderRadius: 8,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
              <span className="mono" style={{ fontSize: 10, fontWeight: 700, color: signalCfg.color, letterSpacing: "0.08em" }}>
                {signal.type === "value" ? "⚡" : "✓"} {signalCfg.label}
              </span>
              {signal.side && (
                <span className="mono" style={{ fontSize: 9, color: signalCfg.color, background: "rgba(0,0,0,0.04)", border: `1px solid ${signalCfg.border}`, borderRadius: 4, padding: "1px 6px" }}>
                  {signal.side === "home" ? homeTeam : signal.side === "away" ? awayTeam : "EMPATE"}
                </span>
              )}
              <span className="mono" style={{ fontSize: 9, color: CONFIDENCE_COLOR[signal.confidence], marginLeft: "auto" }}>
                conf. {signal.confidence}
              </span>
            </div>
            <p style={{ fontSize: 11, color: "var(--text)", lineHeight: 1.6, margin: 0 }}>
              {signal.reasoning}
            </p>
          </div>
        )}

        {signal && signal.type === "none" && (
          <div style={{ padding: "8px 12px", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8 }}>
            <span className="mono" style={{ fontSize: 10, color: "var(--muted)" }}>— Sin señal clara · {signal.reasoning}</span>
          </div>
        )}

        {/* ── Ajuste de probabilidades ── */}
        {data.prob_adjustment && (
          Math.abs(data.prob_adjustment.home) > 0.005 ||
          Math.abs(data.prob_adjustment.draw) > 0.005 ||
          Math.abs(data.prob_adjustment.away) > 0.005
        ) && (
          <div>
            <p className="mono" style={{ fontSize: 9, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 4 }}>
              Ajuste IA sobre modelo
            </p>
            <p style={{ fontSize: 10, color: "var(--muted)", lineHeight: 1.5 }}>
              {data.prob_adjustment.reasoning}
            </p>
          </div>
        )}

        {/* ── Top 3 jugadores locales ── */}
        {data.top_players_home && data.top_players_home.length > 0 && (
          <div>
            <p className="mono" style={{ fontSize: 9, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>
              Claves · {homeTeam}
            </p>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {data.top_players_home.slice(0, 3).map((p, i) => (
                <TopPlayerCard key={i} player={p} />
              ))}
            </div>
          </div>
        )}

        {/* ── Top 3 jugadores visitantes ── */}
        {data.top_players_away && data.top_players_away.length > 0 && (
          <div>
            <p className="mono" style={{ fontSize: 9, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>
              Claves · {awayTeam}
            </p>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {data.top_players_away.slice(0, 3).map((p, i) => (
                <TopPlayerCard key={i} player={p} />
              ))}
            </div>
          </div>
        )}

        {/* ── Factores clave ── */}
        {data.key_factors && data.key_factors.length > 0 && (
          <div>
            <p className="mono" style={{ fontSize: 9, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 4 }}>
              Factores clave
            </p>
            {data.key_factors.map((f, i) => (
              <div key={i} style={{ fontSize: 11, color: "var(--text)", lineHeight: 1.65, display: "flex", gap: 6 }}>
                <span style={{ color: "var(--muted)", flexShrink: 0 }}>·</span>
                <span>{f}</span>
              </div>
            ))}
          </div>
        )}

        {/* ── Bajas ── */}
        {allMissing.length > 0 && (
          <div>
            <p className="mono" style={{ fontSize: 9, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 4 }}>
              Bajas confirmadas
            </p>
            {allMissing.map((p, i) => (
              <div key={i} style={{ fontSize: 10, lineHeight: 1.7, display: "flex", gap: 6, fontFamily: "var(--mono)" }}>
                <span style={{ color: "var(--red, #dc2626)", flexShrink: 0 }}>✕</span>
                <span>
                  <span style={{ color: "var(--text)", fontWeight: 500 }}>{p.name}</span>
                  <span style={{ color: "var(--muted)" }}> · {p.reason} · {p.team}</span>
                </span>
              </div>
            ))}
          </div>
        )}

        {/* ── Forma reciente ── */}
        {(data.form_home || data.form_away) && (
          <div>
            <p className="mono" style={{ fontSize: 9, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 4 }}>
              Forma reciente
            </p>
            {data.form_home && (
              <div className="mono" style={{ fontSize: 10, color: "var(--muted)", lineHeight: 1.7 }}>
                <span style={{ color: "var(--text)", fontWeight: 500 }}>{homeTeam}</span> · {data.form_home}
              </div>
            )}
            {data.form_away && (
              <div className="mono" style={{ fontSize: 10, color: "var(--muted)", lineHeight: 1.7 }}>
                <span style={{ color: "var(--text)", fontWeight: 500 }}>{awayTeam}</span> · {data.form_away}
              </div>
            )}
          </div>
        )}

        {/* ── Contexto ── */}
        {data.context && (
          <div>
            <p className="mono" style={{ fontSize: 9, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 4 }}>
              Contexto
            </p>
            <p style={{ fontSize: 11, color: "var(--text)", lineHeight: 1.65 }}>
              {data.context}
            </p>
          </div>
        )}

        {/* ── Alineaciones del análisis web (si no hay lineup confirmado de API) ── */}
        {data.lineup_confirmed && (data.home_lineup?.length > 0 || data.away_lineup?.length > 0) && (
          <div>
            <p className="mono" style={{ fontSize: 9, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 4 }}>
              Alineación (web)
            </p>
            <div style={{ display: "flex", gap: 16 }}>
              <div style={{ flex: 1 }}>
                <p className="mono" style={{ fontSize: 9, color: "var(--muted)", marginBottom: 3 }}>{homeTeam}</p>
                {(data.home_lineup || []).map((p, i) => (
                  <div key={i} className="mono" style={{ fontSize: 10, color: "var(--text)", lineHeight: 1.7 }}>{p}</div>
                ))}
              </div>
              <div style={{ flex: 1 }}>
                <p className="mono" style={{ fontSize: 9, color: "var(--muted)", marginBottom: 3 }}>{awayTeam}</p>
                {(data.away_lineup || []).map((p, i) => (
                  <div key={i} className="mono" style={{ fontSize: 10, color: "var(--text)", lineHeight: 1.7 }}>{p}</div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ── Fuentes ── */}
        {data.sources && data.sources.length > 0 && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {data.sources.slice(0, 5).map((s, i) => {
              if (!s || typeof s !== "string") return null;
              const domain = s.match(/https?:\/\/(?:www\.)?([^/?#]+)/)?.[1] ?? s.slice(0, 40);
              const href = s.startsWith("http") ? encodeURI(decodeURI(s)) : null;
              if (!href) return (
                <span key={i} className="mono" style={{ fontSize: 9, color: "var(--muted)" }}>
                  {domain}
                </span>
              );
              return (
                <a key={i} href={href} target="_blank" rel="noopener noreferrer"
                  style={{ fontSize: 9, color: "var(--muted)", fontFamily: "var(--mono)", textDecoration: "none" }}>
                  ↗ {domain}
                </a>
              );
            })}
          </div>
        )}

      </div>
    </div>
  );
}
