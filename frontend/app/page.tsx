"use client";

import { useEffect, useState, useCallback } from "react";
import Header from "./components/Header";
import MatchCard from "./components/MatchCard";
import type { AnalysisData } from "./components/AnalysisPanel";

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

  const highValue = matches.filter(m => m.best_value_tier === "high");
  const midValue  = matches.filter(m => m.best_value_tier === "mid");
  const noValue   = matches.filter(m => m.best_value_tier !== "high" && m.best_value_tier !== "mid");

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
