import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "EdgeFút ⚡ — Value Bets del Día",
  description: "Detecta apuestas de valor comparando el modelo Dixon-Coles contra las probabilidades de Polymarket",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className="h-full">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
