"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import TeamFlag from "./TeamFlag";
import { useTimezone, formatInTz } from "../context/TimezoneContext";
import type { AnalysisData } from "./AnalysisPanel";

// Lazy-load modal to keep initial bundle small
const MatchModal = dynamic(() => import("./MatchModal"), { ssr: false });

// ── Types ────────────────────────────────────────────────────────────────────

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
  jersey?: string;
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
  reasons: { text: string; type: string; direction: string }[];
  home_squad: Player[];
  away_squad: Player[];
  lineup_data: LineupData | null;
  analysis_data: AnalysisData | null;
  home_score: number | null;
  away_score: number | null;
  match_status: string;
  analysis_available: boolean;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

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

const PRIOR_PROBS = new Set([0.4, 0.25, 0.35]);
function usesPriors(outcomes: Outcome[]): boolean {
  return outcomes.every(o => PRIOR_PROBS.has(o.model_prob));
}

// ── Compact outcome cell ─────────────────────────────────────────────────────

function OutcomeCell({ o, usePrior }: { o: Outcome; usePrior: boolean }) {
  const LABEL: Record<string, string> = { home: "LOCAL", draw: "EMPATE", away: "VISITA" };
  const hasAiAdj = o.ai_model_prob !== null && o.ai_model_prob !== undefined;
  const ourProb = hasAiAdj ? o.ai_model_prob! : o.model_prob;
  const bestDelta = hasAiAdj && o.ai_delta_pp !== null ? o.ai_delta_pp : o.delta_pp;
  const isHigh = bestDelta !== null && bestDelta >= 10;
  const isMid = bestDelta !== null && bestDelta >= 5 && !isHigh;
  const isValue = isHigh || isMid;
  const color = isHigh ? "var(--green)" : isMid ? "var(--amber)" : "var(--muted)";

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: 1,
      flex: 1,
    }}>
      {/* Label */}
      <div className="mono" style={{
        fontSize: 8,
        textTransform: "uppercase",
        letterSpacing: "0.08em",
        color: "var(--muted)",
        marginBottom: 2,
      }}>
        {LABEL[o.outcome] || o.outcome}
      </div>
      {/* Our prob */}
      <div className="mono" style={{
        fontSize: 13,
        fontWeight: isValue ? 700 : 500,
        color: isValue ? color : "var(--text)",
        lineHeight: 1,
      }}>
        {(ourProb * 100).toFixed(0)}%
        {hasAiAdj && <span style={{ fontSize: 8, fontWeight: 400, marginLeft: 1 }}>IA</span>}
      </div>
      {/* Market prob */}
      <div className="mono" style={{ fontSize: 9, color: "var(--muted)" }}>
        Mercado {o.polymarket_prob !== null ? `${(o.polymarket_prob * 100).toFixed(0)}%` : "—"}
      </div>
    </div>
  );
}

// ── Main card (compact row) ──────────────────────────────────────────────────

export default function MatchCard({ match, delay }: { match: Match; delay: number }) {
  const { tz } = useTimezone();
  const [lineup, setLineup] = useState<LineupData | null>(match.lineup_data);
  const [analysis, setAnalysis] = useState<AnalysisData | null>(match.analysis_data);
  const [open, setOpen] = useState(false);

  const state = getMatchState(match.kickoff, match.match_status);
  const isLive = state === "live";
  const isFinished = state === "finished";
  const isOver = isLive || isFinished;

  const prior = usesPriors(match.outcomes);
  const isHigh = match.best_value_tier === "high";
  const isMid = match.best_value_tier === "mid";
  const showEdge = (isHigh || isMid) && match.best_delta_pp !== null && !isOver;
  const hasAnalysis = !!(analysis?.bet_signal && analysis.bet_signal.type !== "none");
  const hasLineup = !!(lineup?.home_starters?.length);

  const edgeColor = isHigh ? "var(--green)" : "var(--amber)";
  const edgeBg = isHigh ? "#f0fdf4" : "#fffbeb";
  const edgeBorder = isHigh ? "var(--green)" : "var(--amber)";

  return (
    <>
      <article
        className="fade-in"
        onClick={() => setOpen(true)}
        style={{
          animationDelay: `${delay}ms`,
          border: "1px solid var(--border)",
          borderRadius: 10,
          background: "var(--surface)",
          boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
          opacity: isFinished ? 0.6 : 1,
          cursor: "pointer",
          transition: "box-shadow 0.15s, border-color 0.15s",
        }}
        onMouseEnter={e => {
          (e.currentTarget as HTMLElement).style.boxShadow = "0 4px 16px rgba(0,0,0,0.10)";
          (e.currentTarget as HTMLElement).style.borderColor = "#c8c8c4";
        }}
        onMouseLeave={e => {
          (e.currentTarget as HTMLElement).style.boxShadow = "0 1px 3px rgba(0,0,0,0.05)";
          (e.currentTarget as HTMLElement).style.borderColor = "var(--border)";
        }}
      >
        <div style={{
          padding: "14px 16px",
          display: "grid",
          gridTemplateColumns: "minmax(0, 1.6fr) 1fr auto",
          alignItems: "center",
          gap: 12,
        }}>

          {/* ── Left: teams ── */}
          <div style={{ minWidth: 0 }}>
            {/* Home */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
              <TeamFlag team={match.home_team} size={22} />
              <span style={{
                fontSize: 14,
                fontWeight: isFinished && match.home_score !== null && match.away_score !== null && match.home_score > match.away_score ? 700 : 600,
                color: "var(--text)",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
                flex: 1,
              }}>
                {match.home_team}
              </span>
              {isLive && (
                <span style={{
                  fontSize: 8,
                  background: "#fef2f2",
                  color: "#dc2626",
                  padding: "1px 5px",
                  borderRadius: 3,
                  fontFamily: "var(--mono)",
                  fontWeight: 700,
                  letterSpacing: "0.05em",
                  flexShrink: 0,
                }}>● LIVE</span>
              )}
              {isFinished && match.home_score !== null && (
                <span className="mono" style={{
                  fontSize: 16,
                  fontWeight: match.home_score > (match.away_score ?? -1) ? 700 : 400,
                  color: match.home_score > (match.away_score ?? -1) ? "var(--text)" : "var(--muted)",
                  flexShrink: 0,
                  minWidth: 18,
                  textAlign: "right",
                }}>
                  {match.home_score}
                </span>
              )}
            </div>
            {/* Away */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
              <TeamFlag team={match.away_team} size={22} />
              <span style={{
                fontSize: 13,
                fontWeight: isFinished && match.home_score !== null && match.away_score !== null && match.away_score > match.home_score ? 600 : 400,
                color: isFinished && match.home_score !== null && match.away_score !== null && match.away_score > match.home_score ? "var(--text)" : "var(--muted)",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
                flex: 1,
              }}>
                {match.away_team}
              </span>
              {isFinished && match.away_score !== null && (
                <span className="mono" style={{
                  fontSize: 16,
                  fontWeight: match.away_score > (match.home_score ?? -1) ? 700 : 400,
                  color: match.away_score > (match.home_score ?? -1) ? "var(--text)" : "var(--muted)",
                  flexShrink: 0,
                  minWidth: 18,
                  textAlign: "right",
                }}>
                  {match.away_score}
                </span>
              )}
            </div>
            {/* Competition + badges */}
            <div style={{ display: "flex", alignItems: "center", gap: 5, flexWrap: "wrap" }}>
              <span className="mono" style={{ fontSize: 9, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                {match.competition}
              </span>
              {isFinished && (
                <span className="mono" style={{
                  fontSize: 8, background: "var(--bg, #f9fafb)", color: "var(--muted)",
                  padding: "1px 5px", borderRadius: 3, fontWeight: 600,
                  border: "1px solid var(--border)",
                }}>FIN</span>
              )}
              {hasLineup && !isFinished && (
                <span className="mono" style={{
                  fontSize: 8, background: "#f0fdf4", color: "var(--green)",
                  padding: "1px 5px", borderRadius: 3, fontWeight: 600,
                }}>XI</span>
              )}
              {!hasLineup && !isFinished && minutesToKickoff(match.kickoff) <= 150 && minutesToKickoff(match.kickoff) > 0 && (
                <span className="mono" style={{
                  fontSize: 8, background: "#eff6ff", color: "#3b82f6",
                  padding: "1px 5px", borderRadius: 3, fontWeight: 600,
                }}>XI pendiente</span>
              )}
              {hasAnalysis && (
                <span className="mono" style={{
                  fontSize: 8,
                  background: analysis!.bet_signal!.type === "value" ? "#f0fdf4" : "#fffbeb",
                  color: analysis!.bet_signal!.type === "value" ? "var(--green)" : "var(--amber)",
                  padding: "1px 5px", borderRadius: 3, fontWeight: 600,
                }}>
                  Analizado
                </span>
              )}
              {prior && !analysis && (
                <span className="mono" style={{ fontSize: 8, color: "var(--amber)" }}>priors</span>
              )}
            </div>
          </div>

          {/* ── Middle: outcome probabilities ── */}
          <div style={{ display: "flex", gap: 0, justifyContent: "space-between" }}>
            {match.outcomes.map(o => (
              <OutcomeCell key={o.outcome} o={o} usePrior={prior} />
            ))}
          </div>

          {/* ── Right: time + edge badge ── */}
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6, flexShrink: 0 }}>
            <span className="mono" style={{
              fontSize: 12,
              color: isFinished ? "var(--muted)" : "var(--text)",
              fontWeight: 500,
              textDecoration: isFinished ? "none" : "none",
            }}>
              {formatInTz(match.kickoff, tz)}
            </span>
            {(() => {
              // Finished: show signal result if known, otherwise nothing
              if (isFinished) {
                const aiSignal = analysis?.bet_signal;
                if (aiSignal && aiSignal.type !== "none" && aiSignal.side) {
                  const hit = match.home_score !== null && match.away_score !== null && (() => {
                    const hg = match.home_score!, ag = match.away_score!;
                    const actual = hg > ag ? "home" : ag > hg ? "away" : "draw";
                    return actual === aiSignal.side;
                  })();
                  const scoreKnown = match.home_score !== null;
                  if (scoreKnown) {
                    return (
                      <span style={{
                        fontSize: 10, fontFamily: "var(--mono)", fontWeight: 600,
                        color: hit ? "var(--green, #16a34a)" : "var(--red, #dc2626)",
                        background: hit ? "#f0fdf4" : "#fef2f2",
                        border: `1px solid ${hit ? "var(--green, #16a34a)" : "var(--red, #dc2626)"}`,
                        borderRadius: 6, padding: "2px 8px",
                      }}>
                        {hit ? "✓ Acertó" : "✗ Falló"}
                      </span>
                    );
                  }
                }
                return null;
              }
            })()}
            {!isFinished && (() => {
              const aiSignal = analysis?.bet_signal?.type;
              // IA analizó y confirmó → badge positivo
              if (showEdge && aiSignal === "value") {
                return (
                  <span style={{
                    fontSize: 10, fontFamily: "var(--mono)", fontWeight: 700,
                    color: "var(--green)", background: "#f0fdf4",
                    border: "1px solid var(--green)",
                    borderRadius: 6, padding: "2px 8px", letterSpacing: "0.02em",
                  }}>
                    Edge confirmado
                  </span>
                );
              }
              if (aiSignal === "strength") {
                return (
                  <span style={{
                    fontSize: 10, fontFamily: "var(--mono)", fontWeight: 700,
                    color: "#7c3aed", background: "#f5f3ff",
                    border: "1px solid #a78bfa",
                    borderRadius: 6, padding: "2px 8px", letterSpacing: "0.02em",
                  }}>
                    Apuesta de fuerza
                  </span>
                );
              }
              // IA analizó y descartó → mostrar que no hay señal
              if (showEdge && aiSignal === "none") {
                return (
                  <span style={{
                    fontSize: 10, fontFamily: "var(--mono)", fontWeight: 500,
                    color: "var(--muted)",
                    border: "1px solid var(--border)",
                    borderRadius: 6, padding: "2px 8px",
                  }}>
                    IA descarta señal
                  </span>
                );
              }
              // Modelo ve discrepancia pero sin análisis IA todavía
              if (showEdge) {
                return (
                  <span style={{
                    fontSize: 10, fontFamily: "var(--mono)", fontWeight: 600,
                    color: edgeColor, background: edgeBg,
                    border: `1px dashed ${edgeBorder}`,
                    borderRadius: 6, padding: "2px 8px", letterSpacing: "0.02em",
                  }}>
                    Sin analizar
                  </span>
                );
              }
              return (
                <span style={{ fontSize: 9, fontFamily: "var(--mono)", color: "var(--muted)", opacity: 0.6 }}>
                  Ver análisis →
                </span>
              );
            })()}
          </div>
        </div>
      </article>

      {/* Modal */}
      {open && (
        <MatchModal
          match={match}
          onClose={() => setOpen(false)}
          lineup={lineup}
          analysis={analysis}
          onLineupFetched={l => { setLineup(l); }}
          onAnalysisReady={a => { setAnalysis(a); }}
        />
      )}
    </>
  );
}
