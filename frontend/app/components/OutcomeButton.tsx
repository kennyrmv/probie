"use client";
import { useState } from "react";

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

function tierColor(tier: string | null): string {
  if (tier === "high") return "var(--green)";
  if (tier === "mid") return "var(--amber)";
  return "var(--text)";
}

function deltaLabel(tier: string | null, delta: number | null): string {
  if (delta === null) return "";
  const sign = delta >= 0 ? "+" : "";
  if (tier === "high") return `${sign}${delta.toFixed(1)}pp ▲ HIGH`;
  if (tier === "mid") return `${sign}${delta.toFixed(1)}pp ▲ MID`;
  return `${sign}${delta.toFixed(1)}pp`;
}

function outcomeLabel(outcome: string): string {
  if (outcome === "home") return "LOCAL";
  if (outcome === "draw") return "EMPATE";
  return "VISITA";
}

export default function OutcomeButton({ o, usePrior }: { o: Outcome; usePrior: boolean }) {
  const isHigh = o.value_tier === "high";
  const isMid = o.value_tier === "mid";
  const isValue = isHigh || isMid;
  const hasUrl = !!o.polymarket_url;
  const color = tierColor(o.value_tier);
  const hasAiAdj = o.ai_model_prob !== null && o.ai_model_prob !== undefined;

  // AI-adjusted delta tier
  const aiIsHigh = hasAiAdj && o.ai_delta_pp !== null && o.ai_delta_pp >= 10;
  const aiIsMid = hasAiAdj && o.ai_delta_pp !== null && o.ai_delta_pp >= 5 && !aiIsHigh;
  const aiColor = aiIsHigh ? "var(--green)" : aiIsMid ? "var(--amber)" : "var(--muted)";

  const [hovered, setHovered] = useState(false);

  const borderColor = isHigh
    ? "var(--green)"
    : isMid
    ? "var(--amber)"
    : hovered
    ? "#c8c8c4"
    : "var(--border)";

  const bgColor = isHigh
    ? "#f0fdf4"
    : isMid
    ? "#fffbeb"
    : "var(--surface)";

  const inner = (
    <div
      style={{
        flex: 1,
        border: `1px solid ${borderColor}`,
        borderRadius: 8,
        padding: "10px 12px",
        background: bgColor,
        cursor: hasUrl ? "pointer" : "default",
        transition: "border-color 0.15s",
        minWidth: 0,
        display: "flex",
        flexDirection: "column",
        gap: 0,
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Outcome label */}
      <div style={{
        fontSize: 9,
        textTransform: "uppercase",
        letterSpacing: "0.08em",
        color: "var(--muted)",
        marginBottom: 4,
        fontFamily: "var(--sans)",
      }}>
        {outcomeLabel(o.outcome)}
      </div>

      {/* Team / outcome name */}
      <div style={{
        fontSize: 12,
        fontWeight: 500,
        color: isValue ? color : "var(--text)",
        marginBottom: 8,
        lineHeight: 1.3,
      }}>
        {o.label}
      </div>

      {/* Probabilities */}
      <div className="mono" style={{ fontSize: 11, display: "flex", flexDirection: "column", gap: 2 }}>
        <div style={{ color: "var(--muted)" }}>
          <span>Mdo&nbsp;&nbsp;</span>
          <span style={{ color: "var(--text)" }}>
            {o.polymarket_prob !== null ? `${(o.polymarket_prob * 100).toFixed(1)}%` : "—"}
          </span>
        </div>
        <div style={{ color: "var(--muted)" }}>
          <span>Mod&nbsp;&nbsp;</span>
          <span style={{ color: usePrior ? "var(--muted)" : "var(--text)" }}>
            {(o.model_prob * 100).toFixed(1)}%
          </span>
        </div>
        {/* AI-adjusted probability row */}
        {hasAiAdj && (
          <div style={{ color: "var(--muted)" }}>
            <span>IA&nbsp;&nbsp;&nbsp;&nbsp;</span>
            <span style={{ color: aiColor, fontWeight: 500 }}>
              {(o.ai_model_prob! * 100).toFixed(1)}%
            </span>
            {o.ai_delta_pp !== null && Math.abs(o.ai_delta_pp) >= 1 && (
              <span style={{ color: aiColor, fontSize: 9, marginLeft: 4 }}>
                ({o.ai_delta_pp > 0 ? "+" : ""}{o.ai_delta_pp.toFixed(1)}pp)
              </span>
            )}
          </div>
        )}
      </div>

      {/* Delta badge (model vs market) */}
      {o.delta_pp !== null && isValue && (
        <div className="mono" style={{ marginTop: 7, fontSize: 10, color: color, fontWeight: 500 }}>
          {deltaLabel(o.value_tier, o.delta_pp)}
        </div>
      )}

      {/* AI delta badge when AI adjustment pushes into value zone */}
      {hasAiAdj && (aiIsHigh || aiIsMid) && !isValue && o.ai_delta_pp !== null && (
        <div className="mono" style={{ marginTop: 7, fontSize: 10, color: aiColor, fontWeight: 500 }}>
          {o.ai_delta_pp > 0 ? "+" : ""}{o.ai_delta_pp.toFixed(1)}pp IA {aiIsHigh ? "▲ HIGH" : "▲ MID"}
        </div>
      )}
    </div>
  );

  if (hasUrl) {
    return (
      <a
        href={o.polymarket_url!}
        target="_blank"
        rel="noopener noreferrer"
        style={{ flex: 1, textDecoration: "none", display: "flex" }}
      >
        {inner}
      </a>
    );
  }
  return <div style={{ flex: 1, display: "flex" }}>{inner}</div>;
}
