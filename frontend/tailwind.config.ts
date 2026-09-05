import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Dark neon esports palette (mirrors the brand guide tone).
        bg: "#0A0E1A",
        surface: "#131A2E",
        "surface-2": "#1C2540",
        border: "#2A3450",
        primary: "#00E5FF",
        secondary: "#FF2E97",
        accent: "#A855F7",
        // Severity / verdict semantics
        critical: "#FF4D5E",
        warning: "#FFB020",
        info: "#38BDF8",
        success: "#22D39A",
        muted: "#8A97B8",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
      },
      boxShadow: {
        glow: "0 0 20px -2px rgba(0,229,255,0.35)",
        "glow-critical": "0 0 22px -2px rgba(255,77,94,0.45)",
        "glow-warning": "0 0 22px -2px rgba(255,176,32,0.4)",
      },
      keyframes: {
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        "pulse-ring": {
          "0%": { boxShadow: "0 0 0 0 rgba(0,229,255,0.5)" },
          "70%": { boxShadow: "0 0 0 12px rgba(0,229,255,0)" },
          "100%": { boxShadow: "0 0 0 0 rgba(0,229,255,0)" },
        },
      },
      animation: {
        shimmer: "shimmer 1.5s infinite",
        "pulse-ring": "pulse-ring 1.6s cubic-bezier(0.4,0,0.6,1) infinite",
      },
    },
  },
  plugins: [],
};

export default config;
