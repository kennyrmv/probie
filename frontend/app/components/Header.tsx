"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useTimezone, TIMEZONES } from "../context/TimezoneContext";

export default function Header({ lastUpdated }: { lastUpdated: Date | null }) {
  const { tz, setTz } = useTimezone();
  const [time, setTime] = useState("");
  const [lineupError, setLineupError] = useState(false);

  // Clock — ticks every second in selected timezone
  useEffect(() => {
    const tick = () => {
      const now = new Date();
      const timeStr = now.toLocaleTimeString("es", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        timeZone: tz,
      });
      const tzShort = now.toLocaleTimeString("es", {
        timeZone: tz,
        timeZoneName: "short",
      }).split(" ").pop() ?? tz;
      setTime(`${timeStr} ${tzShort}`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [tz, lastUpdated]);

  // Poll /health every 5 min
  useEffect(() => {
    const checkHealth = async () => {
      try {
        const res = await fetch("/health", { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        setLineupError(data.lineup_status === "error");
      } catch {
        // health unreachable — don't show warning
      }
    };
    checkHealth();
    const id = setInterval(checkHealth, 5 * 60 * 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <>
      {/* Lineup API error banner */}
      {lineupError && (
        <div style={{ background: "#fffbeb", borderBottom: "1px solid #fde68a" }}>
          <div style={{ maxWidth: 820, margin: "0 auto", padding: "8px 24px" }}>
            <span className="mono" style={{ fontSize: 11, color: "var(--amber)" }}>
              Backend no disponible
            </span>
          </div>
        </div>
      )}

      <header style={{
        background: "var(--surface)",
        borderBottom: "1px solid var(--border)",
      }}>
        <div style={{
          maxWidth: 820,
          margin: "0 auto",
          padding: "18px 24px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}>
          {/* Left: brand + subtitle */}
          <div>
            <span style={{ fontSize: 20, fontWeight: 700, color: "var(--text)", letterSpacing: "-0.03em", display: "block" }}>
              EdgeFút
            </span>
            <p style={{ fontSize: 11, color: "var(--muted)", marginTop: 2, letterSpacing: "0" }}>
              Value Bets · Dixon-Coles vs Polymarket
            </p>
          </div>

          {/* Right: tz selector + links + clock + live dot */}
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <select
              value={tz}
              onChange={e => setTz(e.target.value)}
              className="mono"
              style={{
                fontSize: 11,
                color: "var(--muted)",
                background: "transparent",
                border: "1px solid var(--border)",
                borderRadius: 5,
                padding: "3px 8px",
                cursor: "pointer",
                outline: "none",
                maxWidth: 140,
              }}
            >
              {!TIMEZONES.find(t => t.value === tz) && (
                <option value={tz}>{tz}</option>
              )}
              {TIMEZONES.map(t => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>

            <Link href="/performance" style={{ fontSize: 11, color: "var(--muted)", textDecoration: "none", fontFamily: "var(--mono)" }}>
              Performance
            </Link>

            <Link href="/bankroll" style={{ fontSize: 11, color: "var(--muted)", textDecoration: "none", fontFamily: "var(--mono)" }}>
              Bankroll
            </Link>

            <span className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>
              {time}
            </span>

            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--green)", display: "inline-block", flexShrink: 0 }} />
          </div>
        </div>
      </header>
    </>
  );
}
