import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { 950: "#05060b", 900: "#090b14", 850: "#0d1020", 800: "#121628", 700: "#1a1f36" },
        brand: { violet: "#8b5cf6", indigo: "#6366f1", cyan: "#22d3ee", emerald: "#34d399", pink: "#f472b6", amber: "#fbbf24" },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "var(--font-inter)", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      keyframes: {
        aurora: { "0%,100%": { transform: "translate(0,0) scale(1)" }, "50%": { transform: "translate(6%,-4%) scale(1.15)" } },
        shimmer: { "0%": { transform: "translateX(-100%)" }, "100%": { transform: "translateX(200%)" } },
        spinslow: { to: { transform: "rotate(360deg)" } },
        blink: { "50%": { opacity: "0" } },
      },
      animation: {
        aurora: "aurora 18s ease-in-out infinite",
        shimmer: "shimmer 1.6s ease-in-out infinite",
        spinslow: "spinslow 3s linear infinite",
        blink: "blink 1s step-end infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
