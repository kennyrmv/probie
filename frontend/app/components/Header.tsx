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
        <div style={{
          background: "#fffbeb",
          borderBottom: "1px solid #fde68a",
          padding: "8px 24px",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}>
          <span style={{ fontSize: 13 }}>⚠️</span>
          <span className="mono" style={{ fontSize: 11, color: "var(--amber)" }}>
            Backend no disponible
          </span>
        </div>
      )}

      <header style={{
        background: "var(--surface)",
        borderBottom: "1px solid var(--border)",
        padding: "16px 24px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
      }}>
        {/* Left: brand + subtitle */}
        <div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
            <span style={{ fontSize: 22, fontWeight: 600, color: "var(--text)", letterSpacing: "-0.02em" }}>
              EdgeFút
            </span>
            <span style={{ fontSize: 18 }}>⚡</span>
          </div>
          <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
            Value Bets · Dixon-Coles vs Polymarket
          </p>
        </div>

        {/* Right: tz selector + bankroll link + clock + live dot */}
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {/* Timezone selector */}
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
              padding: "2px 6px",
              cursor: "pointer",
              outline: "none",
              maxWidth: 130,
            }}
          >
            {/* If current tz not in the list (auto-detected unknown), show it first */}
            {!TIMEZONES.find(t => t.value === tz) && (
              <option value={tz}>{tz}</option>
            )}
            {TIMEZONES.map(t => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>

          <Link
            href="/bankroll"
            style={{ fontSize: 11, color: "var(--muted)", textDecoration: "none", fontFamily: "var(--mono)" }}
          >
            Bankroll →
          </Link>

          <span className="mono" style={{ fontSize: 12, color: "var(--muted)" }}>
            {time}
          </span>

          <span style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: "var(--green)",
            display: "inline-block",
            flexShrink: 0,
          }} />
        </div>
      </header>
    </>
  );
}
