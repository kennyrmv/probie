"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";

interface BetRecord {
  id: string;
  partido: string;
  fecha: string;
  tipo: "VALUE" | "FAV";
  seleccion: string;
  odds: number;
  stake: number;
  resultado: "ganado" | "perdido" | "pendiente";
  pnl: number;
}

function kellyCalc(bankroll: number, p: number, odds: number): { f: number; quarterF: number; stake: number } | null {
  const b = odds - 1;
  if (b <= 0 || p <= 0 || p >= 1) return null;
  const q = 1 - p;
  const f = (b * p - q) / b;
  if (f <= 0) return null;
  const quarterF = f / 4;
  return { f: Math.round(f * 1000) / 10, quarterF: Math.round(quarterF * 1000) / 10, stake: Math.round(bankroll * quarterF) };
}

function saveBets(bets: BetRecord[]) {
  try {
    localStorage.setItem("bet_history", JSON.stringify(bets.slice(-500)));
  } catch {
    alert("Almacenamiento lleno — exporta el historial antes de continuar.");
  }
}

function loadBets(): BetRecord[] {
  try {
    const raw = localStorage.getItem("bet_history");
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export default function BankrollPage() {
  const [capital, setCapital] = useState<number>(1000);
  const [capitalInput, setCapitalInput] = useState<string>("1000");
  const [bets, setBets] = useState<BetRecord[]>([]);

  // Kelly inputs
  const [kellyP, setKellyP] = useState<string>("");
  const [kellyOdds, setKellyOdds] = useState<string>("");

  // New bet form
  const [form, setForm] = useState({
    partido: "",
    tipo: "VALUE" as "VALUE" | "FAV",
    seleccion: "",
    odds: "",
    stake: "",
    resultado: "pendiente" as "ganado" | "perdido" | "pendiente",
  });

  useEffect(() => {
    const saved = localStorage.getItem("bankroll_capital");
    if (saved) {
      const val = parseFloat(saved);
      if (!isNaN(val)) {
        setCapital(val);
        setCapitalInput(String(val));
      }
    }
    setBets(loadBets());
  }, []);

  const saveCapital = useCallback(() => {
    const val = parseFloat(capitalInput);
    if (!isNaN(val) && val > 0) {
      setCapital(val);
      localStorage.setItem("bankroll_capital", String(val));
    }
  }, [capitalInput]);

  const kelly = kellyCalc(capital, parseFloat(kellyP) / 100, parseFloat(kellyOdds));

  const addBet = () => {
    if (!form.partido || !form.seleccion || !form.odds || !form.stake) return;
    const odds = parseFloat(form.odds);
    const stake = parseFloat(form.stake);
    if (isNaN(odds) || isNaN(stake)) return;
    const pnl = form.resultado === "ganado"
      ? Math.round(stake * (odds - 1) * 100) / 100
      : form.resultado === "perdido"
        ? -stake
        : 0;
    const newBet: BetRecord = {
      id: Date.now().toString(),
      partido: form.partido,
      fecha: new Date().toISOString().split("T")[0],
      tipo: form.tipo,
      seleccion: form.seleccion,
      odds,
      stake,
      resultado: form.resultado,
      pnl,
    };
    const updated = [...bets, newBet];
    setBets(updated);
    saveBets(updated);
    setForm({ partido: "", tipo: "VALUE", seleccion: "", odds: "", stake: "", resultado: "pendiente" });
  };

  const setResultado = (id: string, resultado: "ganado" | "perdido" | "pendiente") => {
    const updated = bets.map(b => {
      if (b.id !== id) return b;
      const pnl = resultado === "ganado"
        ? Math.round(b.stake * (b.odds - 1) * 100) / 100
        : resultado === "perdido" ? -b.stake : 0;
      return { ...b, resultado, pnl };
    });
    setBets(updated);
    saveBets(updated);
  };

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(bets, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `edgefut-bets-${new Date().toISOString().split("T")[0]}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const closedBets = bets.filter(b => b.resultado !== "pendiente");
  const totalPnl = closedBets.reduce((sum, b) => sum + b.pnl, 0);
  const roi = closedBets.length > 0
    ? (totalPnl / closedBets.reduce((sum, b) => sum + b.stake, 0)) * 100
    : null;

  const mono: React.CSSProperties = { fontFamily: "var(--mono, monospace)" };

  return (
    <div style={{ maxWidth: 860, margin: "0 auto", padding: "24px 20px 80px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 28 }}>
        <Link href="/" style={{ fontSize: 12, color: "var(--muted, #888)", textDecoration: "none", ...mono }}>
          ← Inicio
        </Link>
        <h1 style={{ fontSize: 18, fontWeight: 600, color: "var(--text, #111)" }}>Bankroll</h1>
      </div>

      {/* Capital + stats row */}
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 28 }}>
        <div style={{ border: "1px solid var(--border, #e5e7eb)", borderRadius: 8, padding: "14px 16px", background: "var(--surface, #fff)", flex: 1, minWidth: 200 }}>
          <p style={{ fontSize: 10, color: "var(--muted, #888)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 8, ...mono }}>Capital</p>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="number"
              value={capitalInput}
              onChange={e => setCapitalInput(e.target.value)}
              onBlur={saveCapital}
              style={{ width: 100, fontSize: 20, fontWeight: 600, border: "none", background: "transparent", color: "var(--text, #111)", outline: "none", ...mono }}
            />
            <span style={{ fontSize: 14, color: "var(--muted, #888)" }}>€</span>
          </div>
        </div>
        {closedBets.length > 0 && (
          <>
            <div style={{ border: "1px solid var(--border, #e5e7eb)", borderRadius: 8, padding: "14px 16px", background: "var(--surface, #fff)", flex: 1, minWidth: 140 }}>
              <p style={{ fontSize: 10, color: "var(--muted, #888)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 8, ...mono }}>P&L Total</p>
              <p style={{ fontSize: 20, fontWeight: 600, color: totalPnl >= 0 ? "var(--green, #16a34a)" : "var(--red, #dc2626)", ...mono }}>
                {totalPnl >= 0 ? "+" : ""}{totalPnl.toFixed(2)}€
              </p>
            </div>
            {roi !== null && (
              <div style={{ border: "1px solid var(--border, #e5e7eb)", borderRadius: 8, padding: "14px 16px", background: "var(--surface, #fff)", flex: 1, minWidth: 140 }}>
                <p style={{ fontSize: 10, color: "var(--muted, #888)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 8, ...mono }}>ROI</p>
                <p style={{ fontSize: 20, fontWeight: 600, color: roi >= 0 ? "var(--green, #16a34a)" : "var(--red, #dc2626)", ...mono }}>
                  {roi >= 0 ? "+" : ""}{roi.toFixed(1)}%
                </p>
              </div>
            )}
          </>
        )}
      </div>

      {/* Kelly calculator */}
      <div style={{ border: "1px solid var(--border, #e5e7eb)", borderRadius: 8, padding: "14px 16px", background: "var(--surface, #fff)", marginBottom: 24 }}>
        <p style={{ fontSize: 10, color: "var(--muted, #888)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 12, ...mono }}>Calculadora Kelly</p>
        <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ fontSize: 10, color: "var(--muted, #888)", ...mono }}>Prob IA (%)</span>
            <input
              type="number"
              min="0"
              max="99"
              value={kellyP}
              onChange={e => setKellyP(e.target.value)}
              placeholder="65"
              style={{ width: 70, fontSize: 14, border: "1px solid var(--border, #e5e7eb)", borderRadius: 5, padding: "4px 8px", ...mono }}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ fontSize: 10, color: "var(--muted, #888)", ...mono }}>Cuota decimal</span>
            <input
              type="number"
              min="1.01"
              step="0.01"
              value={kellyOdds}
              onChange={e => setKellyOdds(e.target.value)}
              placeholder="2.50"
              style={{ width: 80, fontSize: 14, border: "1px solid var(--border, #e5e7eb)", borderRadius: 5, padding: "4px 8px", ...mono }}
            />
          </label>
          {kelly ? (
            <div style={{ ...mono, fontSize: 13, color: "var(--text, #111)", paddingBottom: 4 }}>
              f* = {kelly.f}% · <strong>¼ Kelly = {kelly.quarterF}% = {kelly.stake}€</strong>
            </div>
          ) : kellyP && kellyOdds ? (
            <div style={{ fontSize: 12, color: "var(--muted, #888)", paddingBottom: 4 }}>
              {parseFloat(kellyOdds) <= 1 ? "Cuota inválida (mínimo 1.01)" : "EV negativo — no apostar"}
            </div>
          ) : null}
        </div>
      </div>

      {/* Add bet form */}
      <div style={{ border: "1px solid var(--border, #e5e7eb)", borderRadius: 8, padding: "14px 16px", background: "var(--surface, #fff)", marginBottom: 24 }}>
        <p style={{ fontSize: 10, color: "var(--muted, #888)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 12, ...mono }}>Registrar apuesta</p>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <input
              value={form.partido}
              onChange={e => setForm(f => ({ ...f, partido: e.target.value }))}
              placeholder="Partido (ej: México vs Perú)"
              style={{ flex: 2, minWidth: 200, fontSize: 13, border: "1px solid var(--border, #e5e7eb)", borderRadius: 5, padding: "6px 10px" }}
            />
            <select
              value={form.tipo}
              onChange={e => setForm(f => ({ ...f, tipo: e.target.value as "VALUE" | "FAV" }))}
              style={{ fontSize: 13, border: "1px solid var(--border, #e5e7eb)", borderRadius: 5, padding: "6px 10px", ...mono }}
            >
              <option value="VALUE">VALUE</option>
              <option value="FAV">FAV</option>
            </select>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <input
              value={form.seleccion}
              onChange={e => setForm(f => ({ ...f, seleccion: e.target.value }))}
              placeholder="Selección (ej: México gana)"
              style={{ flex: 2, minWidth: 160, fontSize: 13, border: "1px solid var(--border, #e5e7eb)", borderRadius: 5, padding: "6px 10px" }}
            />
            <input
              type="number"
              value={form.odds}
              onChange={e => setForm(f => ({ ...f, odds: e.target.value }))}
              placeholder="Cuota"
              style={{ width: 80, fontSize: 13, border: "1px solid var(--border, #e5e7eb)", borderRadius: 5, padding: "6px 10px", ...mono }}
            />
            <input
              type="number"
              value={form.stake}
              onChange={e => setForm(f => ({ ...f, stake: e.target.value }))}
              placeholder="Stake €"
              style={{ width: 90, fontSize: 13, border: "1px solid var(--border, #e5e7eb)", borderRadius: 5, padding: "6px 10px", ...mono }}
            />
            <select
              value={form.resultado}
              onChange={e => setForm(f => ({ ...f, resultado: e.target.value as "ganado" | "perdido" | "pendiente" }))}
              style={{ fontSize: 13, border: "1px solid var(--border, #e5e7eb)", borderRadius: 5, padding: "6px 10px" }}
            >
              <option value="pendiente">Pendiente</option>
              <option value="ganado">Ganado</option>
              <option value="perdido">Perdido</option>
            </select>
          </div>
          <button
            onClick={addBet}
            style={{ alignSelf: "flex-start", fontSize: 12, ...mono, background: "var(--text, #111)", color: "var(--surface, #fff)", border: "none", borderRadius: 6, padding: "7px 16px", cursor: "pointer" }}
          >
            + Registrar
          </button>
        </div>
      </div>

      {/* Bet history table */}
      {bets.length > 0 && (
        <div style={{ border: "1px solid var(--border, #e5e7eb)", borderRadius: 8, background: "var(--surface, #fff)", overflow: "hidden" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 16px", borderBottom: "1px solid var(--border, #e5e7eb)" }}>
            <p style={{ fontSize: 10, color: "var(--muted, #888)", textTransform: "uppercase", letterSpacing: "0.1em", ...mono }}>
              Historial · {bets.length} apuestas
            </p>
            <button
              onClick={exportJson}
              style={{ fontSize: 10, ...mono, background: "transparent", border: "1px solid var(--border, #e5e7eb)", borderRadius: 5, padding: "3px 10px", cursor: "pointer", color: "var(--muted, #888)" }}
            >
              Exportar JSON
            </button>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ background: "var(--bg, #f9fafb)" }}>
                  {["Fecha", "Partido", "Tipo", "Selección", "Cuota", "Stake", "Resultado", "P&L"].map(h => (
                    <th key={h} style={{ padding: "8px 12px", textAlign: "left", fontSize: 10, color: "var(--muted, #888)", fontWeight: 500, whiteSpace: "nowrap", ...mono }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...bets].reverse().map(b => (
                  <tr key={b.id} style={{ borderTop: "1px solid var(--border, #e5e7eb)" }}>
                    <td style={{ padding: "8px 12px", color: "var(--muted, #888)", ...mono, whiteSpace: "nowrap" }}>{b.fecha}</td>
                    <td style={{ padding: "8px 12px", color: "var(--text, #111)", maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{b.partido}</td>
                    <td style={{ padding: "8px 12px" }}>
                      <span style={{ ...mono, fontSize: 10, background: b.tipo === "VALUE" ? "#f0fdf4" : "#fffbeb", color: b.tipo === "VALUE" ? "var(--green, #16a34a)" : "var(--amber, #d97706)", padding: "2px 6px", borderRadius: 4 }}>
                        {b.tipo}
                      </span>
                    </td>
                    <td style={{ padding: "8px 12px", color: "var(--text, #111)" }}>{b.seleccion}</td>
                    <td style={{ padding: "8px 12px", ...mono }}>{b.odds.toFixed(2)}</td>
                    <td style={{ padding: "8px 12px", ...mono }}>{b.stake}€</td>
                    <td style={{ padding: "8px 12px" }}>
                      <select
                        value={b.resultado}
                        onChange={e => setResultado(b.id, e.target.value as "ganado" | "perdido" | "pendiente")}
                        style={{ fontSize: 11, border: "1px solid var(--border, #e5e7eb)", borderRadius: 4, padding: "2px 6px", color: b.resultado === "ganado" ? "var(--green, #16a34a)" : b.resultado === "perdido" ? "var(--red, #dc2626)" : "var(--muted, #888)" }}
                      >
                        <option value="pendiente">Pendiente</option>
                        <option value="ganado">Ganado</option>
                        <option value="perdido">Perdido</option>
                      </select>
                    </td>
                    <td style={{ padding: "8px 12px", ...mono, fontWeight: 500, color: b.pnl > 0 ? "var(--green, #16a34a)" : b.pnl < 0 ? "var(--red, #dc2626)" : "var(--muted, #888)" }}>
                      {b.pnl === 0 ? "—" : `${b.pnl > 0 ? "+" : ""}${b.pnl.toFixed(2)}€`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {bets.length === 0 && (
        <div style={{ textAlign: "center", padding: "40px 24px", color: "var(--muted, #888)", fontSize: 13 }}>
          Sin apuestas registradas aún
        </div>
      )}
    </div>
  );
}
