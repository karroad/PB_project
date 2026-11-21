"use client";

import { motion } from "framer-motion";
import type { JobStatus, JobStep } from "@/lib/types";
import { Counter } from "../ui";

const SIZE = 300;
const R = 118;
const C = 2 * Math.PI * R;

const NODE_COLOR: Record<string, string> = {
  completed: "#34d399", running: "#a78bfa", retrying: "#fbbf24", waiting: "#fbbf24", failed: "#f43f5e", pending: "#cbd5e1", skipped: "#475569",
};

export function ProgressOrb({ progress, status, steps, label }: { progress: number; status: JobStatus; steps: JobStep[]; label: string }) {
  const running = status === "running" || status === "queued";
  const done = status === "completed";
  const failed = status === "failed";
  const p = Math.max(0, Math.min(100, progress));
  return (
    <div className="relative mx-auto" style={{ width: SIZE, height: SIZE }}>
      {/* soft rotating glow */}
      <motion.div className="absolute inset-6 rounded-full opacity-30 blur-2xl"
        style={{ background: failed ? "conic-gradient(#f43f5e,#7f1d1d,#f43f5e)" : "conic-gradient(from 0deg,#8b5cf6,#22d3ee,#34d399,#f472b6,#8b5cf6)" }}
        animate={running ? { rotate: 360 } : { rotate: 0 }} transition={running ? { duration: 8, repeat: Infinity, ease: "linear" } : {}} />
      <div className="absolute inset-[34px] rounded-full bg-white shadow-[inset_0_2px_12px_rgba(15,23,42,.08)]" />

      <svg width={SIZE} height={SIZE} className="absolute inset-0 -rotate-90" aria-hidden>
        <defs>
          <linearGradient id="orb-grad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={failed ? "#fb7185" : "#8b5cf6"} />
            <stop offset="50%" stopColor={failed ? "#f43f5e" : "#22d3ee"} />
            <stop offset="100%" stopColor={failed ? "#be123c" : "#34d399"} />
          </linearGradient>
          <filter id="orb-glow"><feGaussianBlur stdDeviation="4" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
        </defs>
        <circle cx={SIZE / 2} cy={SIZE / 2} r={R} fill="none" stroke="rgba(15,23,42,.07)" strokeWidth={12} />
        <motion.circle cx={SIZE / 2} cy={SIZE / 2} r={R} fill="none" stroke="url(#orb-grad)" strokeWidth={12} strokeLinecap="round" filter="url(#orb-glow)"
          strokeDasharray={C} initial={{ strokeDashoffset: C }} animate={{ strokeDashoffset: C * (1 - p / 100) }} transition={{ type: "spring", stiffness: 40, damping: 18 }} />
      </svg>

      {/* comet travelling around the ring while running */}
      {running && (
        <motion.div className="absolute inset-0" animate={{ rotate: 360 }} transition={{ duration: 2.4, repeat: Infinity, ease: "linear" }}>
          <div className="absolute left-1/2 top-[25px] h-3 w-3 -translate-x-1/2 rounded-full bg-violet-500 shadow-[0_0_16px_5px_rgba(139,92,246,.55)]" />
        </motion.div>
      )}

      {/* agent nodes orbiting the ring */}
      {steps.map((s, i) => {
        const a = (i / steps.length) * Math.PI * 2 - Math.PI / 2;
        const x = SIZE / 2 + Math.cos(a) * (R + 26);
        const y = SIZE / 2 + Math.sin(a) * (R + 26);
        const active = s.status === "running" || s.status === "retrying" || s.status === "waiting";
        return (
          <motion.div key={s.key} title={`${s.name} — ${s.status}`} className="absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full"
            style={{ left: x, top: y, background: NODE_COLOR[s.status] ?? "#cbd5e1", boxShadow: s.status === "completed" ? "0 0 10px #34d399" : active ? "0 0 14px #a78bfa" : "none" }}
            initial={{ scale: 0 }} animate={active ? { scale: [1, 1.7, 1] } : { scale: 1 }}
            transition={active ? { duration: 1.2, repeat: Infinity } : { delay: i * 0.04, type: "spring" }} />
        );
      })}

      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
        <motion.div key={done ? "done" : "p"} initial={{ scale: 0.8, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} className="font-display text-6xl font-bold tabular-nums text-slate-900">
          <Counter value={p} />
          <span className="text-2xl text-slate-500">%</span>
        </motion.div>
        <p className="mt-1 max-w-[170px] text-xs uppercase tracking-[0.18em] text-slate-500">{label}</p>
      </div>
    </div>
  );
}
