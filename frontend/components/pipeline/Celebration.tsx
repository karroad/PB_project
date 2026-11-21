"use client";

import { motion } from "framer-motion";
import { useMemo } from "react";

const COLORS = ["#8b5cf6", "#22d3ee", "#34d399", "#f472b6", "#fbbf24", "#ffffff"];

/** One-shot particle burst shown when a website goes live. */
export function Celebration() {
  const parts = useMemo(() => Array.from({ length: 70 }, (_, i) => {
    const a = Math.random() * Math.PI * 2;
    const d = 140 + Math.random() * 320;
    return { i, x: Math.cos(a) * d, y: Math.sin(a) * d - 60, r: Math.random() * 720 - 360, s: 4 + Math.random() * 7, c: COLORS[i % COLORS.length], round: Math.random() > 0.5, delay: Math.random() * 0.15 };
  }), []);
  return (
    <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center" aria-hidden>
      <motion.div className="absolute h-40 w-40 rounded-full bg-emerald-400/30 blur-3xl" initial={{ scale: 0, opacity: 1 }} animate={{ scale: 6, opacity: 0 }} transition={{ duration: 1.4 }} />
      {parts.map((p) => (
        <motion.span key={p.i} className="absolute" style={{ width: p.s, height: p.round ? p.s : p.s * 0.45, background: p.c, borderRadius: p.round ? 999 : 2 }}
          initial={{ x: 0, y: 0, opacity: 1, rotate: 0, scale: 0.4 }}
          animate={{ x: p.x, y: [0, p.y, p.y + 220], opacity: [1, 1, 0], rotate: p.r, scale: 1 }}
          transition={{ duration: 2.2, delay: p.delay, ease: [0.15, 0.7, 0.4, 1], times: [0, 0.45, 1] }} />
      ))}
    </div>
  );
}
