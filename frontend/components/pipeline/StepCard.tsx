"use client";

import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import {
  Brain, Check, ChevronDown, Code2, Eye, Hourglass, Image as ImageIcon, Map as MapIcon, MessageSquareText, Palette, PenTool, Radar, RefreshCw, Rocket, Search, Server, ShieldCheck, X,
} from "lucide-react";
import { useEffect, useState } from "react";
import type { Approval, JobStep } from "@/lib/types";
import { Button } from "../ui";
import { Highlights } from "./Highlights";

export const STEP_ICONS: Record<string, any> = {
  requirements: Brain, planning: MapIcon, branding: Palette, content: PenTool, images: ImageIcon, seo: Search,
  development: Code2, infrastructure: Server, testing: ShieldCheck, deployment: Rocket, verify: Radar, preview: Eye, revise: MessageSquareText,
};

const LEVEL_COLOR = { info: "text-slate-600", success: "text-emerald-700", warning: "text-amber-700", error: "text-rose-700" };

function duration(s: JobStep) {
  if (!s.started_at) return null;
  const end = s.finished_at ? new Date(s.finished_at + (s.finished_at.includes("+") || s.finished_at.endsWith("Z") ? "" : "Z")) : new Date();
  const start = new Date(s.started_at + (s.started_at.includes("+") || s.started_at.endsWith("Z") ? "" : "Z"));
  const sec = Math.max(0, (end.getTime() - start.getTime()) / 1000);
  return sec < 60 ? `${sec.toFixed(1)}s` : `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`;
}

function Node({ step }: { step: JobStep }) {
  const Icon = STEP_ICONS[step.key] ?? Brain;
  const st = step.status;
  return (
    <div className="relative z-10 grid h-11 w-11 shrink-0 place-items-center">
      {(st === "running" || st === "retrying") && (
        <>
          <div className="absolute inset-0 animate-spinslow rounded-full" style={{ background: "conic-gradient(#8b5cf6,#22d3ee,#34d399,transparent 70%)" }} />
          <motion.div className="absolute -inset-2 rounded-full bg-violet-500/30 blur-md" animate={{ opacity: [0.4, 0.9, 0.4] }} transition={{ duration: 1.6, repeat: Infinity }} />
        </>
      )}
      <motion.div
        animate={st === "failed" ? { x: [0, -5, 5, -4, 4, 0] } : {}}
        transition={{ duration: 0.45 }}
        className={clsx("relative grid h-[38px] w-[38px] place-items-center rounded-full border transition-colors duration-500",
          st === "pending" && "border-slate-200 bg-white text-slate-600",
          (st === "running" || st === "retrying") && "border-transparent bg-white text-violet-700",
          st === "completed" && "border-emerald-400/40 bg-emerald-500/15 text-emerald-700 shadow-[0_0_20px_-4px_rgba(52,211,153,.7)]",
          st === "failed" && "border-rose-500/50 bg-rose-500/15 text-rose-700 shadow-[0_0_20px_-4px_rgba(244,63,94,.8)]",
          st === "waiting" && "border-amber-400/50 bg-amber-500/15 text-amber-700",
          st === "skipped" && "border-slate-200 bg-white text-slate-500")}>
        <AnimatePresence mode="wait" initial={false}>
          {st === "completed" ? (
            <motion.svg key="check" viewBox="0 0 24 24" className="h-5 w-5" initial={{ scale: 0.4, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}>
              <motion.path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="currentColor" strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round"
                initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.5, ease: "easeOut" }} />
            </motion.svg>
          ) : st === "failed" ? (
            <motion.span key="x" initial={{ scale: 0 }} animate={{ scale: 1 }}><X className="h-5 w-5" /></motion.span>
          ) : st === "waiting" ? (
            <motion.span key="w" animate={{ rotate: [0, 180, 180, 360] }} transition={{ duration: 2.4, repeat: Infinity }}><Hourglass className="h-4 w-4" /></motion.span>
          ) : st === "retrying" ? (
            <motion.span key="r" animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: "linear" }}><RefreshCw className="h-4 w-4 text-amber-700" /></motion.span>
          ) : (
            <motion.span key="i" initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}><Icon className="h-[18px] w-[18px]" /></motion.span>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  );
}

export function StepCard({ step, index, last, approval, onApprove, onReject, onRetry, busy }: {
  step: JobStep; index: number; last: boolean; approval?: Approval | null; busy?: boolean;
  onApprove?: () => void; onReject?: () => void; onRetry?: () => void;
}) {
  const st = step.status;
  const active = st === "running" || st === "retrying";
  const [open, setOpen] = useState(false);
  const [, tick] = useState(0);
  useEffect(() => { if (!active) return; const t = setInterval(() => tick((x) => x + 1), 500); return () => clearInterval(t); }, [active]);
  const recent = (step.logs || []).slice(-5);
  const err = step.output?.error;

  return (
    <motion.li layout initial={{ opacity: 0, x: -16 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: index * 0.04 }} className="relative flex gap-4 pb-4">
      {!last && (
        <div className="absolute left-[21px] top-12 bottom-0 w-0.5 overflow-hidden rounded-full bg-slate-100">
          <motion.div className="h-full w-full origin-top bg-gradient-to-b from-emerald-400 via-cyan-400 to-violet-500"
            initial={{ scaleY: 0 }} animate={{ scaleY: st === "completed" ? 1 : active ? 0.35 : 0 }} transition={{ duration: 0.8, ease: "easeInOut" }} />
        </div>
      )}
      <Node step={step} />
      <motion.div layout
        className={clsx("min-w-0 flex-1 rounded-2xl border p-4 transition-colors duration-500",
          active ? "glow-border border-transparent bg-white shadow-[0_8px_30px_-12px_rgba(139,92,246,.45)]"
            : st === "completed" ? "border-slate-200 bg-white shadow-sm"
            : st === "failed" ? "border-rose-500/30 bg-rose-500/[0.06]"
            : st === "waiting" ? "border-amber-400/30 bg-amber-500/[0.06]"
            : "border-slate-200 bg-white/70 opacity-70")}>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-mono text-[11px] text-slate-500">{String(index + 1).padStart(2, "0")}</span>
          <h3 className={clsx("font-display text-[15px] font-semibold", st === "pending" ? "text-slate-500" : "text-slate-900")}>{step.name}</h3>
          <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">{step.agent}</span>
          <span className="ml-auto flex items-center gap-2 text-[11px] text-slate-500">
            {step.attempts > 1 && <span className="text-amber-700">attempt {step.attempts}</span>}
            {duration(step) && <span className="tabular-nums">{duration(step)}</span>}
            {active && <span className="tabular-nums text-violet-700">{Math.round(step.progress)}%</span>}
          </span>
        </div>

        {active && (
          <div className="relative mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100">
            <motion.div className="h-full rounded-full bg-grad" animate={{ width: `${Math.max(4, step.progress)}%` }} transition={{ type: "spring", stiffness: 60, damping: 16 }} />
            <div className="absolute inset-y-0 left-0 w-1/3 animate-shimmer bg-gradient-to-r from-transparent via-white/40 to-transparent" />
          </div>
        )}

        {active && (
          <ul className="mt-3 space-y-1 font-mono text-[11.5px]">
            <AnimatePresence initial={false}>
              {recent.map((l, i) => (
                <motion.li key={(step.logs?.length ?? 0) - recent.length + i} layout initial={{ opacity: 0, y: 6, filter: "blur(4px)" }} animate={{ opacity: 1, y: 0, filter: "blur(0px)" }} exit={{ opacity: 0 }}
                  className={clsx("truncate", LEVEL_COLOR[l.level] ?? "text-slate-600", i < recent.length - 1 && "opacity-60")}>
                  <span className="text-violet-600">›</span> {l.message}
                  {i === recent.length - 1 && <span className="ml-0.5 inline-block h-3 w-1.5 translate-y-0.5 animate-blink bg-violet-300" />}
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        )}

        {st === "completed" && step.output?.summary && <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-2 text-sm text-slate-600">{step.output.summary}</motion.p>}
        {st === "completed" && step.output?.highlights && <Highlights items={step.output.highlights} />}

        {st === "waiting" && (
          <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="mt-3 rounded-xl border border-amber-400/20 bg-amber-500/[0.07] p-3">
            <p className="text-sm text-amber-700">{approval?.description || "Waiting for approval"}</p>
            <p className="mt-1 text-xs text-amber-700">This action changes external infrastructure or publishes the site, so a person must approve it.</p>
            {approval && onApprove && (
              <div className="mt-3 flex gap-2">
                <Button size="sm" onClick={onApprove} loading={busy}><Check className="h-3.5 w-3.5" /> Approve</Button>
                <Button size="sm" variant="danger" onClick={onReject} disabled={busy}><X className="h-3.5 w-3.5" /> Reject</Button>
              </div>
            )}
          </motion.div>
        )}

        {st === "failed" && (
          <div className="mt-3 rounded-xl border border-rose-500/20 bg-rose-500/[0.07] p-3">
            <p className="text-sm text-rose-700">{err?.message || step.error}</p>
            {err?.hint && <p className="mt-1 text-xs text-rose-700">💡 {err.hint}</p>}
            {err?.code && <p className="mt-1 font-mono text-[10px] text-rose-700">code: {err.code}</p>}
            {err?.details?.report && <Highlights items={[{ type: "checks", items: err.details.report.checks.filter((c: any) => c.status !== "pass") }]} />}
            {onRetry && <Button size="sm" variant="ghost" className="mt-3" onClick={onRetry} loading={busy}><RefreshCw className="h-3.5 w-3.5" /> Retry from this step</Button>}
          </div>
        )}

        {(step.logs?.length ?? 0) > 0 && !active && (
          <div className="mt-3">
            <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-1 text-[11px] text-slate-500 hover:text-slate-600">
              <ChevronDown className={clsx("h-3.5 w-3.5 transition", open && "rotate-180")} /> {open ? "Hide" : "Show"} logs ({step.logs.length})
            </button>
            <AnimatePresence>
              {open && (
                <motion.ul initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="mt-2 max-h-56 overflow-y-auto rounded-lg bg-slate-50 p-2 font-mono text-[11px]">
                  {step.logs.map((l, i) => <li key={i} className={clsx("py-0.5", LEVEL_COLOR[l.level])}><span className="text-slate-600">{new Date(l.ts).toLocaleTimeString()}</span> {l.message}</li>)}
                </motion.ul>
              )}
            </AnimatePresence>
          </div>
        )}
      </motion.div>
    </motion.li>
  );
}
