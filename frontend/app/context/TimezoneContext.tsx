"use client";
import { createContext, useContext, useEffect, useState } from "react";

const LS_KEY = "edgefut_tz";

interface TzCtx {
  tz: string;
  setTz: (tz: string) => void;
}

const TimezoneContext = createContext<TzCtx>({
  tz: "UTC",
  setTz: () => {},
});

export function TimezoneProvider({ children }: { children: React.ReactNode }) {
  // Start with UTC to avoid hydration mismatch, then resolve client tz
  const [tz, setTzState] = useState("UTC");

  useEffect(() => {
    const saved = localStorage.getItem(LS_KEY);
    if (saved) {
      setTzState(saved);
    } else {
      // Auto-detect browser timezone
      const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
      setTzState(detected);
    }
  }, []);

  const setTz = (newTz: string) => {
    setTzState(newTz);
    localStorage.setItem(LS_KEY, newTz);
  };

  return (
    <TimezoneContext.Provider value={{ tz, setTz }}>
      {children}
    </TimezoneContext.Provider>
  );
}

export function useTimezone() {
  return useContext(TimezoneContext);
}

// Common timezones for the selector
export const TIMEZONES = [
  { value: "Europe/Madrid",       label: "España (CET)" },
  { value: "Europe/London",       label: "Londres (GMT)" },
  { value: "Europe/Paris",        label: "París (CET)" },
  { value: "UTC",                 label: "UTC" },
  { value: "America/New_York",    label: "Nueva York" },
  { value: "America/Chicago",     label: "Chicago" },
  { value: "America/Mexico_City", label: "México" },
  { value: "America/Bogota",      label: "Colombia" },
  { value: "America/Lima",        label: "Perú" },
  { value: "America/Santiago",    label: "Chile" },
  { value: "America/Sao_Paulo",   label: "Brasil" },
  { value: "America/Buenos_Aires",label: "Argentina" },
  { value: "Africa/Lagos",        label: "Nigeria" },
  { value: "Africa/Dakar",        label: "Senegal" },
  { value: "Africa/Cairo",        label: "Egipto" },
  { value: "Asia/Riyadh",        label: "Arabia Saudita" },
  { value: "Asia/Tokyo",          label: "Japón" },
  { value: "Asia/Seoul",          label: "Corea" },
  { value: "Asia/Shanghai",       label: "China" },
  { value: "Australia/Sydney",    label: "Australia" },
];

/** Format a UTC ISO string into the given timezone, returning e.g. "22:30 CET" */
export function formatInTz(iso: string, tz: string): string {
  try {
    const d = new Date(iso);
    const time = d.toLocaleTimeString("es", {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: tz,
    });
    // Get short timezone name (CET, GMT-5, etc.)
    const tzName = d.toLocaleTimeString("es", {
      timeZone: tz,
      timeZoneName: "short",
    }).split(" ").pop() ?? tz;
    return `${time} ${tzName}`;
  } catch {
    return iso;
  }
}
