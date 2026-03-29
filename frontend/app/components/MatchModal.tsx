"use client";

import { useEffect, useRef, useState } from "react";
import TeamFlag from "./TeamFlag";
import AnalysisPanel from "./AnalysisPanel";
import { useTimezone, formatInTz } from "../context/TimezoneContext";
import type { AnalysisData } from "./AnalysisPanel";

// ── Types (mirrored from MatchCard) ─────────────────────────────────────────

interface Outcome {
  outcome: string;
  label: string;
  polymarket_prob: number | null;
  model_prob: number;
  ai_model_prob: number | null;
  ai_delta_pp: number | null;
  delta_pp: number | null;
  value_tier: string | null;
  polymarket_url: string | null;
}

interface Player {
  name: string;
  position: string;
  nationality?: string;
}

interface MissingPlayer {
  name: string;
  reason: string;
  type: string;
}

interface LineupData {
  source: string;
  fetched_at: string;
  api_fixture_id?: number;
  home_formation: string;
  away_formation: string;
  home_starters: Player[];
  home_subs: Player[];
  away_starters: Player[];
  away_subs: Player[];
  home_missing: MissingPlayer[];
  away_missing: MissingPlayer[];
  lineup_confirmed?: boolean;
}

interface Match {
  id: string;
  home_team: string;
  away_team: string;
  kickoff: string;
  competition: string;
  best_value_tier: string;
  best_delta_pp: number | null;
  outcomes: Outcome[];
  lineup_data: LineupData | null;
  analysis_data: AnalysisData | null;
  home_score: number | null;
  away_score: number | null;
  match_status: string;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function posAbbr(pos: string): string {
  if (pos === "Goalkeeper" || pos === "G") return "GK";
  if (pos === "Defence" || pos === "D") return "DEF";
  if (pos === "Midfield" || pos === "M") return "MID";
  if (pos === "Offence" || pos === "F" || pos === "A") return "FWD";
  return pos;
}

function minutesToKickoff(iso: string): number {
  return (new Date(iso).getTime() - Date.now()) / 60000;
}

function getMatchState(kickoff: string, dbStatus: string): "scheduled" | "live" | "finished" {
  if (dbStatus === "finished") return "finished";
  const minsSince = -minutesToKickoff(kickoff);
  if (minsSince < 0) return "scheduled";
  if (minsSince < 120) return "live";
  return "finished";
}

// ── Lineup panel inside modal ────────────────────────────────────────────────

function ModalLineupPanel({ match, lineup }: { match: Match; lineup: LineupData }) {
  if (!lineup || lineup.home_starters.length === 0) return null;
  const confirmed = !!lineup.lineup_confirmed;

  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <span style={{
          fontSize: 9,
          textTransform: "uppercase",
          letterSpacing: "0.1em",
          color: "var(--muted)",
          fontFamily: "var(--mono)",
        }}>
          {confirmed ? "XI Confirmado" : "XI Probable"}
        </span>
        {confirmed && (
          <span style={{
            fontSize: 9, background: "#f0fdf4", color: "var(--green)",
            padding: "1px 6px", borderRadius: 3, fontFamily: "var(--mono)", fontWeight: 600,
          }}>✓ OFICIAL</span>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {/* Home */}
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
            <TeamFlag team={match.home_team} size={16} />
            <span style={{ fontSize: 11, fontWeight: 600, color: "var(--text)" }}>
              {match.home_team}
            </span>
            {lineup.home_formation && (
              <span className="mono" style={{ fontSize: 9, color: "var(--muted)", marginLeft: "auto" }}>
                {lineup.home_formation}
              </span>
            )}
          </div>
          {lineup.home_starters.slice(0, 11).map((p, i) => (
            <div key={i} className="mono" style={{ fontSize: 10, lineHeight: 1.75, display: "flex", gap: 6 }}>
              <span style={{ color: "var(--muted)", minWidth: 28 }}>{posAbbr(p.position)}</span>
              <span style={{ color: "var(--text)" }}>{p.name}</span>
            </div>
          ))}
          {(lineup.home_missing || []).length > 0 && (
            <div style={{ marginTop: 6, paddingTop: 6, borderTop: "1px solid var(--border)" }}>
              {lineup.home_missing.map((p, i) => (
                <div key={i} className="mono" style={{ fontSize: 9, color: "#dc2626", lineHeight: 1.7 }}>
                  ✕ {p.name} · {p.reason}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Away */}
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
            <TeamFlag team={match.away_team} size={16} />
            <span style={{ fontSize: 11, fontWeight: 600, color: "var(--text)" }}>
              {match.away_team}
            </span>
            {lineup.away_formation && (
              <span className="mono" style={{ fontSize: 9, color: "var(--muted)", marginLeft: "auto" }}>
                {lineup.away_formation}
              </span>
            )}
          </div>
          {lineup.away_starters.slice(0, 11).map((p, i) => (
            <div key={i} className="mono" style={{ fontSize: 10, lineHeight: 1.75, display: "flex", gap: 6 }}>
              <span style={{ color: "var(--muted)", minWidth: 28 }}>{posAbbr(p.position)}</span>
              <span style={{ color: "var(--text)" }}>{p.name}</span>
            </div>
          ))}
          {(lineup.away_missing || []).length > 0 && (
            <div style={{ marginTop: 6, paddingTop: 6, borderTop: "1px solid var(--border)" }}>
              {lineup.away_missing.map((p, i) => (
                <div key={i} className="mono" style={{ fontSize: 9, color: "#dc2626", lineHeight: 1.7 }}>
                  ✕ {p.name} · {p.reason}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Lineup fetch button (modal variant) ─────────────────────────────────────

function ModalLineupButton({
  matchId,
  kickoff,
  hasProbableLineup,
  onLineupFetched,
  onAnalysisReady,
}: {
  matchId: string;
  kickoff: string;
  hasProbableLineup: boolean;
  onLineupFetched: (lineup: LineupData) => void;
  onAnalysisReady: (analysis: AnalysisData) => void;
}) {
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  const minsToKickoff = minutesToKickoff(kickoff);
  const isClose = minsToKickoff <= 90;

  const startPolling = () => {
    setPolling(true);
    setMessage("Analizando…");
    let polls = 0;
    pollRef.current = setInterval(async () => {
      polls++;
      try {
        const res = await fetch("/api/matches/today", { cache: "no-store" });
        const data: Match[] = await res.json();
        const updated = data.find((m: Match) => m.id === matchId);
        if (updated?.analysis_data) {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          setPolling(false);
          setMessage(null);
          onAnalysisReady(updated.analysis_data);
          return;
        }
      } catch { /* silently retry */ }
      if (polls >= 4) {
        clearInterval(pollRef.current!);
        pollRef.current = null;
        setPolling(false);
        setMessage("Análisis no disponible aún");
      }
    }, 30_000);
  };

  const fetchLineup = async () => {
    setLoading(true);
    setMessage(null);
    try {
      const res = await fetch(`/api/matches/${matchId}/fetch-lineup`, { method: "POST" });
      const ct = res.headers.get("content-type") ?? "";
      if (!ct.includes("application/json")) throw new Error(`Error del servidor (HTTP ${res.status})`);
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`);
      if (json.status === "ok" && json.lineup) {
        onLineupFetched(json.lineup);
        if (json.auto_analysis_triggered) startPolling();
      } else {
        setMessage(json.message || "Alineación no disponible aún");
      }
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Error al obtener alineación");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <button
        onClick={fetchLineup}
        disabled={loading}
        style={{
          fontSize: 11,
          fontFamily: "var(--mono)",
          color: isClose ? "var(--green)" : "var(--muted)",
          background: "var(--bg)",
          border: `1px solid ${isClose ? "var(--green)" : "var(--border)"}`,
          borderRadius: 6,
          padding: "5px 14px",
          cursor: loading ? "wait" : "pointer",
          display: "flex",
          alignItems: "center",
          gap: 6,
          opacity: loading ? 0.6 : 1,
        }}
      >
        {loading ? "⏳" : "📋"}{" "}
        {loading ? "Buscando…" : hasProbableLineup ? "Actualizar XI oficial" : "Ver Alineación"}
        {!loading && !isClose && (
          <span style={{ color: "var(--muted)", fontSize: 9 }}>({Math.round(minsToKickoff / 60)}h)</span>
        )}
      </button>
      {message && (
        <span className="mono" style={{ fontSize: 10, color: "var(--muted)" }}>{message}</span>
      )}
    </div>
  );
}

// ── Outcome row inside modal ─────────────────────────────────────────────────

function ModalOutcomeRow({
  outcomes,
  analysis,
}: {
  outcomes: Outcome[];
  analysis: AnalysisData | null;
}) {
  const LABEL: Record<string, string> = { home: "LOCAL", draw: "EMPATE", away: "VISITA" };
  const aiSignal = analysis?.bet_signal;
  // When there's an AI signal (value or strength), only that side gets the badge
  const hasAiSignal = !!(aiSignal && aiSignal.type !== "none" && aiSignal.side);

  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "repeat(3, 1fr)",
      gap: 8,
      marginBottom: 20,
    }}>
      {outcomes.map(o => {
        const hasAiAdj = o.ai_model_prob !== null && o.ai_model_prob !== undefined;
        const ourProb = hasAiAdj ? o.ai_model_prob! : o.model_prob;
        const bestDelta = hasAiAdj && o.ai_delta_pp !== null ? o.ai_delta_pp : o.delta_pp;

        // Determine highlight: AI signal takes precedence over raw model delta
        const isAiPick = hasAiSignal && aiSignal!.side === o.outcome;
        const isValueType = aiSignal?.type === "value";
        const isStrengthType = aiSignal?.type === "strength";

        // Model-based highlight only when no AI signal present
        const modelIsHigh = !hasAiSignal && bestDelta !== null && bestDelta >= 10;
        const modelIsMid  = !hasAiSignal && bestDelta !== null && bestDelta >= 5 && !modelIsHigh;

        // Final highlight decision
        const highlight = isAiPick || modelIsHigh || modelIsMid;
        const color = isAiPick
          ? (isStrengthType ? "#7c3aed" : "var(--green)")
          : modelIsHigh ? "var(--green)" : modelIsMid ? "var(--amber)" : "var(--text)";
        const borderColor = isAiPick
          ? (isStrengthType ? "#a78bfa" : "var(--green)")
          : modelIsHigh ? "var(--green)" : modelIsMid ? "var(--amber)" : "var(--border)";
        const bgColor = isAiPick
          ? (isStrengthType ? "#f5f3ff" : "#f0fdf4")
          : modelIsHigh ? "#f0fdf4" : modelIsMid ? "#fffbeb" : "var(--surface)";

        // Badge label
        const badgeLabel = isAiPick
          ? (isValueType ? "⚡ IA confirma valor" : "💪 IA recomienda")
          : modelIsHigh ? "⚡ El mercado lo infravalora"
          : "↑ Ligera ventaja";

        const inner = (
          <div style={{
            padding: "10px 12px",
            border: `1px solid ${borderColor}`,
            borderRadius: 8,
            background: bgColor,
            display: "flex",
            flexDirection: "column",
            gap: 2,
          }}>
            <div className="mono" style={{ fontSize: 9, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 2 }}>
              {LABEL[o.outcome] || o.outcome}
            </div>
            <div style={{ fontSize: 13, fontWeight: 600, color: highlight ? color : "var(--text)", marginBottom: 4 }}>
              {o.label}
            </div>
            <div className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>
              <span style={{ color: highlight ? color : "var(--text)", fontWeight: highlight ? 600 : 400 }}>
                Nosotros {(ourProb * 100).toFixed(0)}%
              </span>
              {hasAiAdj && <span style={{ fontSize: 8, marginLeft: 2 }}>IA</span>}
            </div>
            <div className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>
              Mercado {o.polymarket_prob !== null ? `${(o.polymarket_prob * 100).toFixed(0)}%` : "—"}
            </div>
            {(isAiPick || modelIsHigh || modelIsMid) && (
              <div className="mono" style={{ fontSize: 10, color, fontWeight: 600, marginTop: 5 }}>
                {badgeLabel}
              </div>
            )}
          </div>
        );

        if (o.polymarket_url) {
          return (
            <a key={o.outcome} href={o.polymarket_url} target="_blank" rel="noopener noreferrer" style={{ textDecoration: "none" }}>
              {inner}
            </a>
          );
        }
        return <div key={o.outcome}>{inner}</div>;
      })}
    </div>
  );
}

// ── Main modal ───────────────────────────────────────────────────────────────

export default function MatchModal({
  match,
  onClose,
  lineup,
  analysis,
  onLineupFetched,
  onAnalysisReady,
}: {
  match: Match;
  onClose: () => void;
  lineup: LineupData | null;
  analysis: AnalysisData | null;
  onLineupFetched: (l: LineupData) => void;
  onAnalysisReady: (a: AnalysisData) => void;
}) {
  const { tz } = useTimezone();
  const state = getMatchState(match.kickoff, match.match_status);
  const isLive = state === "live";
  const isFinished = state === "finished";
  const isOver = isLive || isFinished;

  const hasStarters = !!(lineup?.home_starters?.length);
  const isLineupConfirmed = !!(lineup?.lineup_confirmed);
  const minsToKickoff = minutesToKickoff(match.kickoff);
  const showLineupButton = !isOver && minsToKickoff > -120 && (!hasStarters || !isLineupConfirmed);

  // Trap focus + Escape key
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handleKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        zIndex: 1000,
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        padding: "40px 16px 40px",
        overflowY: "auto",
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: 14,
          width: "100%",
          maxWidth: 680,
          boxShadow: "0 20px 60px rgba(0,0,0,0.18)",
          overflow: "hidden",
          animation: "slideUp 0.18s ease-out",
        }}
      >
        {/* Modal header */}
        <div style={{
          padding: "20px 24px 16px",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
        }}>
          {/* Teams */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0, flex: 1 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <TeamFlag team={match.home_team} size={28} />
              <span style={{ fontSize: 16, fontWeight: 700, color: "var(--text)" }}>{match.home_team}</span>
            </div>
            <span style={{ fontSize: 13, color: "var(--muted)", flexShrink: 0 }}>
              {isFinished && match.home_score !== null && match.away_score !== null
                ? `${match.home_score} – ${match.away_score}`
                : isLive ? "●" : "vs"}
            </span>
            <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <TeamFlag team={match.away_team} size={28} />
              <span style={{ fontSize: 16, fontWeight: 700, color: "var(--text)" }}>{match.away_team}</span>
            </div>
          </div>

          {/* Meta + close */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
            <div style={{ textAlign: "right" }}>
              {isLive && (
                <div style={{ fontSize: 9, fontFamily: "var(--mono)", color: "#dc2626", fontWeight: 700, marginBottom: 2 }}>● LIVE</div>
              )}
              <div className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>
                {formatInTz(match.kickoff, tz)}
              </div>
              <div className="mono" style={{ fontSize: 9, color: "var(--muted)", marginTop: 1 }}>
                {match.competition}
              </div>
            </div>
            <button
              onClick={onClose}
              style={{
                width: 30, height: 30, borderRadius: "50%",
                border: "1px solid var(--border)",
                background: "var(--bg)",
                cursor: "pointer",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 14, color: "var(--muted)",
                flexShrink: 0,
              }}
            >✕</button>
          </div>
        </div>

        {/* Modal body */}
        <div style={{ padding: "20px 24px 24px" }}>

          {/* Outcome probabilities */}
          <ModalOutcomeRow outcomes={match.outcomes} analysis={analysis} />

          {/* Lineup */}
          {hasStarters && <ModalLineupPanel match={match} lineup={lineup!} />}

          {/* Lineup fetch button */}
          {showLineupButton && (
            <div style={{ marginBottom: 20 }}>
              <ModalLineupButton
                matchId={match.id}
                kickoff={match.kickoff}
                hasProbableLineup={hasStarters && !isLineupConfirmed}
                onLineupFetched={onLineupFetched}
                onAnalysisReady={onAnalysisReady}
              />
            </div>
          )}

          {/* Analysis */}
          <AnalysisPanel
            matchId={match.id}
            homeTeam={match.home_team}
            awayTeam={match.away_team}
            initialData={analysis}
          />
        </div>
      </div>

      <style>{`
        @keyframes slideUp {
          from { opacity: 0; transform: translateY(16px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
