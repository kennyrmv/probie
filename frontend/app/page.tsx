"use client";

import { useEffect, useState, useCallback } from "react";
import Header from "./components/Header";
import MatchCard from "./components/MatchCard";
import type { AnalysisData } from "./components/AnalysisPanel";

function getKellyAmount(
  bankroll: number,
  p: number,
  odds: number
): { pct: number; amount: number } | null {
  const b = odds - 1;
  if (b <= 0 || p <= 0 || p >= 1) return null;
  const q = 1 - p;
  const f = (b * p - q) / b;
  if (f <= 0) return null;
  const quarterKelly = f / 4;
  return { pct: Math.round(quarterKelly * 1000) / 10, amount: Math.round(bankroll * quarterKelly) };
}

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

interface LineupData {
  source: string;
  fetched_at: string;
  api_fixture_id?: number;
  home_formation: string;
  away_formation: string;
  home_starters: { name: string; position: string; nationality?: string; jersey?: string }[];
  home_subs: { name: string; position: string; nationality?: string; jersey?: string }[];
  away_starters: { name: string; position: string; nationality?: string; jersey?: string }[];
  away_subs: { name: string; position: string; nationality?: string; jersey?: string }[];
  home_missing: { name: string; reason: string; type: string }[];
  away_missing: { name: string; reason: string; type: string }[];
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
  home_squad: { name: string; position: string; nationality: string }[];
  away_squad: { name: string; position: string; nationality: string }[];
  lineup_data: LineupData | null;
  analysis_data: AnalysisData | null;
  home_score: number | null;
  away_score: number | null;
  match_status: string;
}

function getMatchState(kickoff: string, dbStatus: string): "scheduled" | "live" | "finished" {
  if (dbStatus === "finished") return "finished";
  const minsSince = (Date.now() - new Date(kickoff).getTime()) / 60000;
  if (minsSince < 0) return "scheduled";
  if (minsSince < 120) return "live";
  return "finished";
}

interface BetCard {
  match: Match;
  type: "value" | "favorite";
  side: "home" | "draw" | "away";
  label: string;
  ourProb: number | null;
  marketProb: number | null;
  edgePp: number | null;
  confidence: "alta" | "media" | "baja";
  reasoning: string;
  hasAnalysis: boolean;
}

function pickBestBets(matches: Match[]): { value: BetCard | null; favorite: BetCard | null } {
  const scheduled = matches.filter(m => getMatchState(m.kickoff, m.match_status) === "scheduled");

  // ── Best VALUE: highest edge from model, enriched with analysis if available ──
  let bestValue: BetCard | null = null;
  let bestValueEdge = -Infinity;

  for (const m of scheduled) {
    if (!m.best_delta_pp || m.best_delta_pp < 5) continue; // minimum 5pp edge

    const signal = m.analysis_data?.bet_signal;

    if (signal && signal.type === "value" && signal.side) {
      // Analysis agrees: use analyzed side + reasoning
      const outcome = m.outcomes.find(o => o.outcome === signal.side);
      if (!outcome) continue;
      const edgePp = outcome.ai_delta_pp ?? outcome.delta_pp;
      if (edgePp !== null && edgePp > bestValueEdge) {
        bestValueEdge = edgePp;
        bestValue = {
          match: m, type: "value",
          side: signal.side as "home" | "draw" | "away",
          label: outcome.label,
          ourProb: outcome.ai_model_prob ?? outcome.model_prob,
          marketProb: outcome.polymarket_prob,
          edgePp,
          confidence: signal.confidence,
          reasoning: signal.reasoning,
          hasAnalysis: true,
        };
      }
    } else if (!m.analysis_data) {
      // No analysis at all: fall back to model — pick the outcome with highest delta
      const bestOutcome = m.outcomes.reduce<Outcome | null>((best, o) => {
        const d = o.ai_delta_pp ?? o.delta_pp;
        const bd = best ? (best.ai_delta_pp ?? best.delta_pp) : null;
        if (d === null) return best;
        if (bd === null || d > bd) return o;
        return best;
      }, null);
      if (!bestOutcome) continue;
      const edgePp = bestOutcome.ai_delta_pp ?? bestOutcome.delta_pp;
      if (edgePp !== null && edgePp > bestValueEdge) {
        bestValueEdge = edgePp;
        bestValue = {
          match: m, type: "value",
          side: bestOutcome.outcome as "home" | "draw" | "away",
          label: bestOutcome.label,
          ourProb: bestOutcome.ai_model_prob ?? bestOutcome.model_prob,
          marketProb: bestOutcome.polymarket_prob,
          edgePp,
          confidence: "media",
          reasoning: "",
          hasAnalysis: false,
        };
      }
    }
  }

  // ── Best FAVORITE: requires analysis to know which side to back ──
  let bestFav: BetCard | null = null;
  let bestFavProb = -Infinity;

  for (const m of scheduled) {
    const signal = m.analysis_data?.bet_signal;
    if (!signal || signal.type !== "favorite" || !signal.side) continue;
    const outcome = m.outcomes.find(o => o.outcome === signal.side);
    if (!outcome) continue;
    const ourProb = outcome.ai_model_prob ?? outcome.model_prob;
    if (ourProb > bestFavProb) {
      bestFavProb = ourProb;
      bestFav = {
        match: m, type: "favorite",
        side: signal.side as "home" | "draw" | "away",
        label: outcome.label,
        ourProb,
        marketProb: outcome.polymarket_prob,
        edgePp: outcome.ai_delta_pp ?? outcome.delta_pp,
        confidence: signal.confidence,
        reasoning: signal.reasoning,
        hasAnalysis: true,
      };
    }
  }

  return { value: bestValue, favorite: bestFav };
}

function BetCardBox({ card, bankroll }: { card: BetCard; bankroll: number }) {
  const isValue = card.type === "value";
  const accentColor = isValue ? "var(--green)" : "var(--amber)";
  const bg = isValue ? "#f0fdf4" : "#fffbeb";
  const kelly = card.ourProb ? getKellyAmount(bankroll, card.ourProb, 2.0) : null;

  return (
    <div style={{
      flex: 1,
      border: `1.5px solid ${accentColor}`,
      borderRadius: 8,
      padding: "12px 14px",
      background: bg,
      display: "flex",
      flexDirection: "column",
      gap: 6,
      minWidth: 0,
    }}>
      {/* Tipo de señal */}
      <span className="mono" style={{ fontSize: 9, color: accentColor, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em" }}>
        {isValue ? "⚡ Oportunidad detectada" : "✓ Favorito con valor"}
      </span>

      {/* Resultado recomendado */}
      <div style={{ fontWeight: 700, fontSize: 14, color: "var(--text)", lineHeight: 1.2 }}>
        {card.label}
      </div>
      <div className="mono" style={{ fontSize: 10, color: "var(--muted)" }}>
        {card.match.home_team} vs {card.match.away_team}
      </div>

      {/* Comparativa de probabilidades — el corazón de la señal */}
      {card.ourProb !== null && (
        <div style={{
          display: "flex", gap: 12, alignItems: "center",
          padding: "8px 10px",
          background: "rgba(0,0,0,0.04)",
          borderRadius: 6,
          marginTop: 2,
        }}>
          <div style={{ textAlign: "center" }}>
            <div className="mono" style={{ fontSize: 16, fontWeight: 700, color: accentColor, lineHeight: 1 }}>
              {Math.round(card.ourProb * 100)}%
            </div>
            <div style={{ fontSize: 9, color: "var(--muted)", marginTop: 2 }}>Nuestro modelo</div>
          </div>
          <div style={{ fontSize: 16, color: "var(--muted)", fontWeight: 300 }}>vs</div>
          <div style={{ textAlign: "center" }}>
            <div className="mono" style={{ fontSize: 16, fontWeight: 700, color: "var(--muted)", lineHeight: 1 }}>
              {card.marketProb !== null ? `${Math.round(card.marketProb * 100)}%` : "—"}
            </div>
            <div style={{ fontSize: 9, color: "var(--muted)", marginTop: 2 }}>Mercado</div>
          </div>
          {card.marketProb !== null && card.ourProb !== null && (
            <div style={{ marginLeft: "auto", textAlign: "right" }}>
              <div className="mono" style={{ fontSize: 11, fontWeight: 700, color: accentColor }}>
                +{Math.round((card.ourProb - card.marketProb) * 100)}%
              </div>
              <div style={{ fontSize: 9, color: "var(--muted)", marginTop: 2 }}>de diferencia</div>
            </div>
          )}
        </div>
      )}

      {/* Razonamiento IA (si está disponible) */}
      {card.hasAnalysis && card.reasoning && (
        <div style={{
          fontSize: 11, color: "var(--text)", lineHeight: 1.55,
          display: "-webkit-box", WebkitLineClamp: 3,
          WebkitBoxOrient: "vertical", overflow: "hidden",
        }}>
          {card.reasoning}
        </div>
      )}
      {!card.hasAnalysis && (
        <div className="mono" style={{ fontSize: 10, color: "var(--muted)", fontStyle: "italic" }}>
          Señal del modelo matemático · Analiza para ver razonamiento IA
        </div>
      )}

      {/* Apuesta sugerida */}
      {kelly && (
        <div className="mono" style={{ fontSize: 10, color: "var(--text)", marginTop: 2 }}>
          Apuesta sugerida: {kelly.pct}% de bankroll · {kelly.amount}€
        </div>
      )}
    </div>
  );
}

function VeredictoDia({ matches, bankroll }: { matches: Match[]; bankroll: number }) {
  const { value, favorite } = pickBestBets(matches);
  if (!value && !favorite) return null;

  return (
    <div style={{
      border: "1px solid var(--border)",
      borderRadius: 10,
      background: "var(--surface)",
      boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
      padding: "14px 16px",
      marginBottom: 24,
    }}>
      <p className="mono" style={{ fontSize: 11, color: "var(--muted)", marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.1em" }}>
        Veredicto del día
      </p>
      {(!value && !favorite) ? (
        <p style={{ fontSize: 13, color: "var(--muted)" }}>No hay apuestas recomendadas hoy</p>
      ) : (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          {value && <BetCardBox card={value} bankroll={bankroll} />}
          {favorite && <BetCardBox card={favorite} bankroll={bankroll} />}
        </div>
      )}
    </div>
  );
}

function SkeletonCard() {
  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 10,
        overflow: "hidden",
        background: "var(--surface)",
        boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
      }}
    >
      <div style={{ padding: "14px 16px 10px", display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, flex: 1 }}>
          <div className="skeleton" style={{ width: "60%", height: 18 }} />
          <div className="skeleton" style={{ width: 80, height: 10 }} />
        </div>
        <div className="skeleton" style={{ width: 60, height: 14, flexShrink: 0 }} />
      </div>
      <div style={{ padding: "0 16px 14px", display: "flex", gap: 8 }}>
        {[0, 1, 2].map(i => (
          <div key={i} className="skeleton" style={{ flex: 1, height: 90, borderRadius: 8 }} />
        ))}
      </div>
    </div>
  );
}

const REFRESH_INTERVAL = 5 * 60 * 1000;

export default function HomePage() {
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [bankroll, setBankroll] = useState<number>(1000);

  useEffect(() => {
    const saved = localStorage.getItem("bankroll_capital");
    if (saved) setBankroll(parseFloat(saved) || 1000);
  }, []);

  const fetchMatches = useCallback(async () => {
    try {
      const res = await fetch("/api/matches/today", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: Match[] = await res.json();
      data.sort((a, b) => {
        if (a.best_delta_pp === null && b.best_delta_pp === null) return 0;
        if (a.best_delta_pp === null) return 1;
        if (b.best_delta_pp === null) return -1;
        return b.best_delta_pp - a.best_delta_pp;
      });
      setMatches(data);
      setLastUpdated(new Date());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error desconocido");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMatches();
    const id = setInterval(fetchMatches, REFRESH_INTERVAL);
    return () => clearInterval(id);
  }, [fetchMatches]);

  const scheduled = matches.filter(m => getMatchState(m.kickoff, m.match_status) === "scheduled");
  const liveOrFinished = matches.filter(m => getMatchState(m.kickoff, m.match_status) !== "scheduled");

  const highValue = scheduled.filter(m => m.best_value_tier === "high");
  const midValue  = scheduled.filter(m => m.best_value_tier === "mid");
  const noValue   = scheduled.filter(m => m.best_value_tier !== "high" && m.best_value_tier !== "mid");

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: "100vh" }}>
      <Header lastUpdated={lastUpdated} />

      <main style={{ flex: 1, maxWidth: 860, width: "100%", margin: "0 auto", padding: "24px 20px 48px" }}>

        {/* Error state */}
        {error && (
          <div
            style={{
              border: "1px solid #fecaca",
              borderRadius: 8,
              padding: "12px 16px",
              background: "#fef2f2",
              marginBottom: 24,
            }}
          >
            <span className="mono" style={{ fontSize: 11, color: "var(--red)" }}>
              Error conectando al backend — {error}
            </span>
          </div>
        )}

        {/* Loading skeletons */}
        {loading && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {[0, 1, 2].map(i => <SkeletonCard key={i} />)}
          </div>
        )}

        {/* Empty state */}
        {!loading && !error && matches.length === 0 && (
          <div style={{ textAlign: "center", padding: "80px 24px" }}>
            <p style={{ fontSize: 14, color: "var(--muted)" }}>No hay partidos hoy</p>
          </div>
        )}

        {/* Match sections */}
        {!loading && matches.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>

            <VeredictoDia matches={matches} bankroll={bankroll} />

            {highValue.length > 0 && (
              <section>
                <p
                  className="mono"
                  style={{ fontSize: 11, color: "var(--muted)", marginBottom: 10 }}
                >
                  Alta rentabilidad · {highValue.length} {highValue.length === 1 ? "partido" : "partidos"}
                </p>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {highValue.map((m, i) => (
                    <MatchCard key={m.id} match={m} delay={i * 50} />
                  ))}
                </div>
              </section>
            )}

            {midValue.length > 0 && (
              <section>
                <p
                  className="mono"
                  style={{ fontSize: 11, color: "var(--muted)", marginBottom: 10 }}
                >
                  Rentabilidad media · {midValue.length} {midValue.length === 1 ? "partido" : "partidos"}
                </p>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {midValue.map((m, i) => (
                    <MatchCard key={m.id} match={m} delay={i * 50} />
                  ))}
                </div>
              </section>
            )}

            {noValue.length > 0 && (
              <section>
                <p
                  className="mono"
                  style={{ fontSize: 11, color: "var(--muted)", marginBottom: 10 }}
                >
                  Sin edge · {noValue.length} {noValue.length === 1 ? "partido" : "partidos"}
                </p>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {noValue.map((m, i) => (
                    <MatchCard key={m.id} match={m} delay={i * 50} />
                  ))}
                </div>
              </section>
            )}

            {liveOrFinished.length > 0 && (
              <section>
                <p
                  className="mono"
                  style={{ fontSize: 11, color: "var(--muted)", marginBottom: 10 }}
                >
                  En curso / finalizados · {liveOrFinished.length} {liveOrFinished.length === 1 ? "partido" : "partidos"}
                </p>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {liveOrFinished.map((m, i) => (
                    <MatchCard key={m.id} match={m} delay={i * 50} />
                  ))}
                </div>
              </section>
            )}

          </div>
        )}
      </main>

      <footer style={{ padding: "16px 24px", textAlign: "center" }}>
        <span style={{ fontSize: 10, color: "var(--muted)" }}>
          Modelo Dixon-Coles · Polymarket + football-data.org · Solo informativo
        </span>
      </footer>
    </div>
  );
}
