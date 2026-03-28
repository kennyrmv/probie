"use client";

import { useState, useEffect, useRef } from "react";
import OutcomeButton from "./OutcomeButton";
import AnalysisPanel from "./AnalysisPanel";
import TeamFlag from "./TeamFlag";
import { useTimezone, formatInTz } from "../context/TimezoneContext";
import type { AnalysisData } from "./AnalysisPanel";

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
}

function posAbbr(pos: string): string {
  if (pos === "Goalkeeper" || pos === "G") return "GK";
  if (pos === "Defence" || pos === "D") return "DEF";
  if (pos === "Midfield" || pos === "M") return "MID";
  if (pos === "Offence" || pos === "F" || pos === "A") return "FWD";
  return pos;
}

// formatKickoff now comes from TimezoneContext (formatInTz)

function minutesToKickoff(iso: string): number {
  return (new Date(iso).getTime() - Date.now()) / 60000;
}

// Returns "scheduled" | "live" | "finished"
// Uses kickoff time: live = last 120min, finished = >120min ago
function getMatchState(kickoff: string, dbStatus: string): "scheduled" | "live" | "finished" {
  if (dbStatus === "finished") return "finished";
  const minsSince = -minutesToKickoff(kickoff); // positive = started
  if (minsSince < 0) return "scheduled";
  if (minsSince < 120) return "live";
  return "finished";
}

const PRIOR_PROBS = new Set([0.4, 0.25, 0.35]);
function usesPriors(outcomes: Outcome[]): boolean {
  return outcomes.every(o => PRIOR_PROBS.has(o.model_prob));
}

// ─── Confirmed lineup panel ────────────────────────────────────────────────

function LineupPanel({ match, lineup }: { match: Match; lineup: LineupData }) {
  if (!lineup || lineup.home_starters.length === 0) return null;

  return (
    <div style={{ padding: "8px 16px 12px", borderTop: "1px solid var(--border)" }}>
      {/* Formation badges */}
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
        <span className="mono" style={{ fontSize: 9, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.1em" }}>
          {match.home_team} · {lineup.home_formation || "—"}
        </span>
        <span className="mono" style={{ fontSize: 9, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.1em" }}>
          {lineup.away_formation || "—"} · {match.away_team}
        </span>
      </div>

      <div style={{ display: "flex", gap: 16 }}>
        <div style={{ flex: 1 }}>
          {lineup.home_starters.slice(0, 11).map((p, i) => (
            <div key={i} className="mono" style={{ fontSize: 10, color: "var(--muted)", lineHeight: 1.7 }}>
              <span style={{ color: "var(--text)", fontWeight: 500 }}>{p.name}</span>
              {" · "}{posAbbr(p.position)}
            </div>
          ))}
          {(lineup.home_missing || []).length > 0 && (
            <div style={{ marginTop: 4 }}>
              {lineup.home_missing.map((p, i) => (
                <div key={i} className="mono" style={{ fontSize: 10, color: "var(--red, #dc2626)", lineHeight: 1.7 }}>
                  ✕ {p.name} · {p.reason}
                </div>
              ))}
            </div>
          )}
        </div>
        <div style={{ flex: 1 }}>
          {lineup.away_starters.slice(0, 11).map((p, i) => (
            <div key={i} className="mono" style={{ fontSize: 10, color: "var(--muted)", lineHeight: 1.7 }}>
              <span style={{ color: "var(--text)", fontWeight: 500 }}>{p.name}</span>
              {" · "}{posAbbr(p.position)}
            </div>
          ))}
          {(lineup.away_missing || []).length > 0 && (
            <div style={{ marginTop: 4 }}>
              {lineup.away_missing.map((p, i) => (
                <div key={i} className="mono" style={{ fontSize: 10, color: "var(--red, #dc2626)", lineHeight: 1.7 }}>
                  ✕ {p.name} · {p.reason}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div style={{ marginTop: 6 }}>
        <span className="mono" style={{ fontSize: 9, color: "var(--muted)" }}>
          Alineación confirmada · {lineup.source === "claude+duckduckgo" ? "IA+Web" : "API-Football"}
        </span>
      </div>
    </div>
  );
}

// ─── Squad fallback panel ──────────────────────────────────────────────────

function SquadPanel({ match, hasConfirmedLineup }: { match: Match; hasConfirmedLineup: boolean }) {
  if (hasConfirmedLineup) return null;
  if (!match.home_squad?.length && !match.away_squad?.length) return null;

  return (
    <div style={{ padding: "8px 16px 12px", borderTop: "1px solid var(--border)" }}>
      <div style={{ display: "flex", gap: 16 }}>
        <div style={{ flex: 1 }}>
          <p style={{ fontSize: 9, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6, fontFamily: "var(--mono)" }}>
            {match.home_team}
          </p>
          {(match.home_squad || []).slice(0, 6).map((p, i) => (
            <div key={i} className="mono" style={{ fontSize: 10, color: "var(--muted)", lineHeight: 1.7 }}>
              <span style={{ color: "var(--text)", fontWeight: 500 }}>{p.name}</span>
              {" · "}{posAbbr(p.position)}{p.nationality ? ` · ${p.nationality}` : ""}
            </div>
          ))}
        </div>
        <div style={{ flex: 1 }}>
          <p style={{ fontSize: 9, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6, fontFamily: "var(--mono)" }}>
            {match.away_team}
          </p>
          {(match.away_squad || []).slice(0, 6).map((p, i) => (
            <div key={i} className="mono" style={{ fontSize: 10, color: "var(--muted)", lineHeight: 1.7 }}>
              <span style={{ color: "var(--text)", fontWeight: 500 }}>{p.name}</span>
              {" · "}{posAbbr(p.position)}{p.nationality ? ` · ${p.nationality}` : ""}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Lineup fetch button ───────────────────────────────────────────────────

function LineupFetchButton({
  matchId,
  kickoff,
  onLineupFetched,
  onAnalysisReady,
}: {
  matchId: string;
  kickoff: string;
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
  const isClose = minsToKickoff <= 90;   // within 90min of kickoff

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
      } catch {
        // silently retry
      }
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
      const res = await fetch(`/api/matches/${matchId}/fetch-lineup`, {
        method: "POST",
      });
      const ct = res.headers.get("content-type") ?? "";
      if (!ct.includes("application/json")) {
        throw new Error(`Error del servidor (HTTP ${res.status})`);
      }
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`);
      if (json.status === "ok" && json.lineup) {
        onLineupFetched(json.lineup);
        if (json.auto_analysis_triggered) {
          startPolling();
        }
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
          fontSize: 10,
          fontFamily: "var(--mono)",
          color: isClose ? "var(--green)" : "var(--muted)",
          background: "var(--bg)",
          border: `1px solid ${isClose ? "var(--green)" : "var(--border)"}`,
          borderRadius: 5,
          padding: "3px 10px",
          cursor: loading ? "wait" : "pointer",
          display: "flex",
          alignItems: "center",
          gap: 5,
          opacity: loading ? 0.6 : 1,
        }}
      >
        {loading ? "⏳" : "📋"} {loading ? "Buscando…" : "Ver Alineación"}
        {!loading && !isClose && (
          <span style={{ color: "var(--muted)", fontSize: 9 }}>({Math.round(minsToKickoff / 60)}h)</span>
        )}
      </button>
      {message && (
        <span className="mono" style={{ fontSize: 9, color: "var(--muted)" }}>{message}</span>
      )}
    </div>
  );
}

// ─── Main card ────────────────────────────────────────────────────────────

export default function MatchCard({ match, delay }: { match: Match; delay: number }) {
  const { tz } = useTimezone();
  const [lineup, setLineup] = useState<LineupData | null>(match.lineup_data);
  const [analysis, setAnalysis] = useState<AnalysisData | null>(match.analysis_data);

  const state = getMatchState(match.kickoff, match.match_status);
  const isLive = state === "live";
  const isFinished = state === "finished";
  const isOver = isLive || isFinished;

  const prior = usesPriors(match.outcomes);
  const isHigh = match.best_value_tier === "high";
  const isMid = match.best_value_tier === "mid";
  const showValueBadge = (isHigh || isMid) && match.best_delta_pp !== null && !isOver;

  const badgeColor = isHigh ? "var(--green)" : "var(--amber)";
  const deltaSign = match.best_delta_pp !== null && match.best_delta_pp >= 0 ? "+" : "";

  const hasConfirmedLineup = !!(lineup?.home_starters?.length);
  const minsToKickoff = minutesToKickoff(match.kickoff);
  const showLineupButton = !hasConfirmedLineup && minsToKickoff > -120 && !isOver;

  return (
    <article
      className="fade-in"
      style={{
        animationDelay: `${delay}ms`,
        border: `1px solid ${isOver ? "var(--border)" : "var(--border)"}`,
        borderRadius: 10,
        overflow: "hidden",
        background: "var(--surface)",
        boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
        opacity: isFinished ? 0.65 : 1,
      }}
    >
      {/* Card header */}
      <div style={{ padding: "12px 16px 10px" }}>
        {/* Teams row with flags */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 8 }}>
          {/* Home team */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0, flex: 1 }}>
            <TeamFlag team={match.home_team} size={26} />
            <span style={{
              fontSize: 14,
              fontWeight: 600,
              color: "var(--text)",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}>
              {match.home_team}
            </span>
          </div>

          {/* Center: vs / score / live */}
          <div style={{ flexShrink: 0, display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
            {isLive && (
              <span className="mono" style={{
                fontSize: 8,
                background: "#fef2f2",
                color: "#dc2626",
                padding: "1px 5px",
                borderRadius: 3,
                fontWeight: 700,
                letterSpacing: "0.06em",
              }}>● LIVE</span>
            )}
            {isFinished ? (
              <span className="mono" style={{
                fontSize: 13,
                fontWeight: 700,
                color: "var(--muted)",
                letterSpacing: "0.05em",
              }}>
                {match.home_score !== null && match.away_score !== null
                  ? `${match.home_score} – ${match.away_score}`
                  : "FIN"}
              </span>
            ) : (
              <span style={{ fontSize: 11, color: "var(--muted)", fontWeight: 400 }}>vs</span>
            )}
          </div>

          {/* Away team */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0, flex: 1, justifyContent: "flex-end" }}>
            <span style={{
              fontSize: 14,
              fontWeight: 600,
              color: "var(--text)",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
              textAlign: "right",
            }}>
              {match.away_team}
            </span>
            <TeamFlag team={match.away_team} size={26} />
          </div>
        </div>

        {/* Competition + kickoff row */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{
            fontSize: 9,
            textTransform: "uppercase",
            letterSpacing: "0.1em",
            color: "var(--muted)",
            fontFamily: "var(--mono)",
          }}>
            {match.competition}
          </span>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            {!isOver && hasConfirmedLineup && (
              <span className="mono" style={{
                fontSize: 9, background: "#f0fdf4", color: "var(--green)",
                padding: "2px 5px", borderRadius: 4, fontWeight: 500,
              }}>XI</span>
            )}
            {!isOver && match.analysis_data?.bet_signal && match.analysis_data.bet_signal.type !== "none" && (
              <span className="mono" style={{
                fontSize: 9,
                background: match.analysis_data.bet_signal.type === "value" ? "#f0fdf4" : "#fffbeb",
                color: match.analysis_data.bet_signal.type === "value" ? "var(--green)" : "var(--amber)",
                padding: "2px 5px", borderRadius: 4, fontWeight: 500,
              }}>
                {match.analysis_data.bet_signal.type === "value" ? "⚡ EDGE" : "✓ FAV"}
              </span>
            )}
            {showValueBadge && (
              <span className="mono" style={{ fontSize: 10, color: badgeColor, fontWeight: 500 }}>
                {deltaSign}{match.best_delta_pp!.toFixed(1)}pp
              </span>
            )}
            <span className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>
              {formatInTz(match.kickoff, tz)}
            </span>
          </div>
        </div>

        {/* Prior warning */}
        {prior && !analysis && (
          <div style={{ marginTop: 5 }}>
            <span style={{ fontSize: 10, color: "var(--amber)", fontFamily: "var(--mono)" }}>⚠ Usando priors de liga</span>
          </div>
        )}
      </div>

      {/* Outcomes row */}
      <div style={{ padding: "0 16px 14px", display: "flex", gap: 8 }}>
        {match.outcomes.map(o => (
          <OutcomeButton key={o.outcome} o={o} usePrior={prior} />
        ))}
      </div>

      {/* Lineup fetch button — shown when no confirmed lineup */}
      {showLineupButton && (
        <div style={{ padding: "0 16px 12px", borderTop: "1px solid var(--border)", paddingTop: 10 }}>
          <LineupFetchButton
            matchId={match.id}
            kickoff={match.kickoff}
            onLineupFetched={setLineup}
            onAnalysisReady={setAnalysis}
          />
        </div>
      )}

      {/* Confirmed lineup panel */}
      {hasConfirmedLineup && <LineupPanel match={match} lineup={lineup!} />}

      {/* Squad fallback */}
      <SquadPanel match={match} hasConfirmedLineup={hasConfirmedLineup} />

      {/* AI analysis panel */}
      <AnalysisPanel
        matchId={match.id}
        homeTeam={match.home_team}
        awayTeam={match.away_team}
        initialData={analysis}
      />

      {/* Reasons */}
      {match.reasons && match.reasons.length > 0 && (
        <div style={{ padding: "8px 16px 12px", borderTop: "1px solid var(--border)" }}>
          <span style={{ fontSize: 10, color: "var(--muted)" }}>
            {match.reasons.map((r, i) => (
              <span key={i}>
                {i > 0 && <span style={{ margin: "0 5px" }}>·</span>}
                {r.text}
              </span>
            ))}
          </span>
        </div>
      )}
    </article>
  );
}
