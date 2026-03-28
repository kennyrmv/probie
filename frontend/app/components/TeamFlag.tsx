"use client";
import { useState } from "react";

// ISO 3166-1 alpha-2 country codes — covers all major football nations
const COUNTRY_CODES: Record<string, string> = {
  // South America
  Argentina: "ar", Brasil: "br", Brazil: "br", Colombia: "co",
  Uruguay: "uy", Peru: "pe", "Perú": "pe", Chile: "cl",
  Ecuador: "ec", Paraguay: "py", Bolivia: "bo", Venezuela: "ve",
  // Africa
  Senegal: "sn", Morocco: "ma", Marruecos: "ma", Egypt: "eg",
  Egipto: "eg", Nigeria: "ng", Ghana: "gh", Cameroon: "cm",
  "Camerún": "cm", "Ivory Coast": "ci", "Côte d'Ivoire": "ci",
  "Costa de Marfil": "ci", Algeria: "dz", Argelia: "dz",
  Tunisia: "tn", "Túnez": "tn", "South Africa": "za", "Sudáfrica": "za",
  Mali: "ml", Burkina: "bf", "Burkina Faso": "bf", Guinea: "gn",
  Zambia: "zm", Zimbabwe: "zw", Kenya: "ke", Tanzania: "tz",
  Ethiopia: "et", "DR Congo": "cd", Congo: "cg", Angola: "ao",
  Mozambique: "mz", Uganda: "ug", Rwanda: "rw", Gabon: "ga",
  Benin: "bj", Togo: "tg", Mauritania: "mr", "Cape Verde": "cv",
  "Cabo Verde": "cv", Libya: "ly", Sudan: "sd",
  // Europe
  Spain: "es", "España": "es", France: "fr", Francia: "fr",
  Germany: "de", Alemania: "de", England: "gb-eng", Inglaterra: "gb-eng",
  Italy: "it", Italia: "it", Portugal: "pt", Netherlands: "nl",
  "Países Bajos": "nl", Holanda: "nl", Belgium: "be", "Bélgica": "be",
  Croatia: "hr", Croacia: "hr", Switzerland: "ch", Suiza: "ch",
  Denmark: "dk", Dinamarca: "dk", Sweden: "se", Suecia: "se",
  Poland: "pl", Polonia: "pl", Ukraine: "ua", Ucrania: "ua",
  Austria: "at", "Czech Republic": "cz", "República Checa": "cz",
  Hungary: "hu", "Hungría": "hu", Scotland: "gb-sct", Escocia: "gb-sct",
  Wales: "gb-wls", Gales: "gb-wls", Serbia: "rs", Romania: "ro",
  Rumania: "ro", Slovakia: "sk", Eslovaquia: "sk", Slovenia: "si",
  Eslovenia: "si", Turkey: "tr", "Turquía": "tr", Greece: "gr",
  Grecia: "gr", Iceland: "is", Islandia: "is", Norway: "no",
  Noruega: "no", Finland: "fi", Finlandia: "fi", Russia: "ru",
  Rusia: "ru", Albania: "al", "Bosnia and Herzegovina": "ba",
  Bosnia: "ba", Montenegro: "me", Kosovo: "xk", "North Macedonia": "mk",
  Macedonia: "mk", Bulgaria: "bg", Estonia: "ee", Latvia: "lv",
  Lithuania: "lt", "Northern Ireland": "gb-nir",
  Belarus: "by", Bielorrusia: "by", Georgia: "ge", Armenia: "am",
  Azerbaijan: "az", Kazakhstan: "kz",
  // North & Central America
  USA: "us", "United States": "us", "Estados Unidos": "us",
  Mexico: "mx", "México": "mx", Canada: "ca", "Canadá": "ca",
  "Costa Rica": "cr", Panama: "pa", "Panamá": "pa", Honduras: "hn",
  Jamaica: "jm", Guatemala: "gt", "El Salvador": "sv", Haiti: "ht",
  Cuba: "cu", "Trinidad and Tobago": "tt",
  // Asia / Oceania
  Japan: "jp", "Japón": "jp", "South Korea": "kr", "Corea del Sur": "kr",
  China: "cn", Australia: "au", Iran: "ir", "Irán": "ir",
  "Saudi Arabia": "sa", "Arabia Saudita": "sa", Qatar: "qa",
  UAE: "ae", "United Arab Emirates": "ae", Iraq: "iq", Syria: "sy",
  Jordan: "jo", Lebanon: "lb", Uzbekistan: "uz", Kyrgyzstan: "kg",
  "New Zealand": "nz", Indonesia: "id", Thailand: "th", Vietnam: "vn",
  India: "in", Pakistan: "pk", Bangladesh: "bd",
};

// Generate a stable background color from team name
function teamColor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xffffff;
  const hue = h % 360;
  return `hsl(${hue}, 55%, 45%)`;
}

function initials(name: string): string {
  return name
    .split(/[\s-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(w => w[0].toUpperCase())
    .join("");
}

interface TeamFlagProps {
  team: string;
  size?: number; // height in px
}

export default function TeamFlag({ team, size = 28 }: TeamFlagProps) {
  const code = COUNTRY_CODES[team];
  const [failed, setFailed] = useState(false);

  if (code && !failed) {
    return (
      <img
        src={`https://flagcdn.com/h${Math.round(size * 1.5)}/${code}.png`}
        alt={team}
        height={size}
        onError={() => setFailed(true)}
        style={{
          height: size,
          width: "auto",
          borderRadius: 3,
          boxShadow: "0 1px 3px rgba(0,0,0,0.18)",
          display: "block",
          flexShrink: 0,
          objectFit: "cover",
        }}
      />
    );
  }

  // Fallback: colored initials badge for club teams
  return (
    <div
      style={{
        height: size,
        width: size * 1.3,
        borderRadius: 3,
        background: teamColor(team),
        color: "#fff",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: size * 0.38,
        fontWeight: 700,
        letterSpacing: "0.02em",
        flexShrink: 0,
        fontFamily: "var(--mono)",
      }}
    >
      {initials(team)}
    </div>
  );
}
