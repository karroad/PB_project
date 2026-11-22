"use client";

import clsx from "clsx";
import { AnimatePresence, animate, motion, useMotionValue, useTransform } from "framer-motion";
import { Loader2, X } from "lucide-react";
import { useEffect } from "react";
import type { Health, SiteStatus } from "@/lib/types";

export function Button({ variant = "primary", size = "md", loading, className, children, ...p }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" | "subtle"; size?: "sm" | "md" | "lg"; loading?: boolean }) {
  return (
    <button {...p} disabled={p.disabled || loading}
      className={clsx("relative inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl font-medium transition active:scale-[.98] disabled:cursor-not-allowed disabled:opacity-50",
        { sm: "px-3 py-1.5 text-xs", md: "px-4 py-2 text-sm", lg: "px-6 py-3 text-base" }[size],
        variant === "primary" && "bg-grad text-white shadow-lg shadow-violet-600/25 hover:shadow-violet-500/40 hover:brightness-110",
        variant === "ghost" && "border border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100",
        variant === "subtle" && "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
        variant === "danger" && "border border-rose-500/30 bg-rose-500/10 text-rose-700 hover:bg-rose-500/20",
        className)}>
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  );
}

export function Card({ className, children, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div {...p} className={clsx("glass p-5", className)}>{children}</div>;
}

const STATUS: Record<string, { label: string; cls: string; dot: string }> = {
  draft: { label: "Draft", cls: "bg-slate-500/10 text-slate-600 border-slate-500/20", dot: "bg-slate-400" },
  queued: { label: "Queued", cls: "bg-slate-500/10 text-slate-600 border-slate-500/20", dot: "bg-slate-400" },
  preview: { label: "Preview ready", cls: "bg-sky-50 text-sky-700 border-sky-200", dot: "bg-sky-500" },
  generating: { label: "Generating", cls: "bg-violet-500/10 text-violet-700 border-violet-500/30", dot: "bg-violet-400 animate-pulse" },
  running: { label: "Running", cls: "bg-violet-500/10 text-violet-700 border-violet-500/30", dot: "bg-violet-400 animate-pulse" },
  awaiting_approval: { label: "Needs approval", cls: "bg-amber-500/10 text-amber-700 border-amber-500/30", dot: "bg-amber-400 animate-pulse" },
  live: { label: "Live", cls: "bg-emerald-500/10 text-emerald-700 border-emerald-500/30", dot: "bg-emerald-400" },
  completed: { label: "Completed", cls: "bg-emerald-500/10 text-emerald-700 border-emerald-500/30", dot: "bg-emerald-400" },
  failed: { label: "Failed", cls: "bg-rose-500/10 text-rose-700 border-rose-500/30", dot: "bg-rose-400" },
  cancelled: { label: "Cancelled", cls: "bg-slate-500/10 text-slate-600 border-slate-500/20", dot: "bg-slate-500" },
  archived: { label: "Archived", cls: "bg-slate-500/10 text-slate-500 border-slate-500/20", dot: "bg-slate-600" },
  active: { label: "Active", cls: "bg-emerald-500/10 text-emerald-700 border-emerald-500/30", dot: "bg-emerald-400" },
  superseded: { label: "Superseded", cls: "bg-slate-500/10 text-slate-500 border-slate-500/20", dot: "bg-slate-500" },
  rolled_back: { label: "Rolled back", cls: "bg-amber-500/10 text-amber-700 border-amber-500/30", dot: "bg-amber-400" },
  verifying: { label: "Verifying", cls: "bg-cyan-500/10 text-cyan-700 border-cyan-500/30", dot: "bg-cyan-400 animate-pulse" },
  pending: { label: "Pending", cls: "bg-amber-500/10 text-amber-700 border-amber-500/30", dot: "bg-amber-400" },
  approved: { label: "Approved", cls: "bg-emerald-500/10 text-emerald-700 border-emerald-500/30", dot: "bg-emerald-400" },
  rejected: { label: "Rejected", cls: "bg-rose-500/10 text-rose-700 border-rose-500/30", dot: "bg-rose-400" },
  ready: { label: "Ready", cls: "bg-emerald-50 text-emerald-700 border-emerald-200", dot: "bg-emerald-500" },
  provisioning: { label: "Preparing", cls: "bg-violet-50 text-violet-700 border-violet-200", dot: "bg-violet-500 animate-pulse" },
  new: { label: "Not checked", cls: "bg-slate-50 text-slate-600 border-slate-200", dot: "bg-slate-400" },
  ok: { label: "Connected", cls: "bg-emerald-500/10 text-emerald-700 border-emerald-500/30", dot: "bg-emerald-400" },
  error: { label: "Error", cls: "bg-rose-500/10 text-rose-700 border-rose-500/30", dot: "bg-rose-400" },
  unverified: { label: "Unverified", cls: "bg-slate-500/10 text-slate-600 border-slate-500/20", dot: "bg-slate-400" },
};

export function StatusBadge({ status }: { status: SiteStatus | string }) {
  const s = STATUS[status] ?? { label: status, cls: "bg-slate-500/10 text-slate-600 border-slate-500/20", dot: "bg-slate-400" };
  return <span className={clsx("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[11px] font-medium", s.cls)}><span className={clsx("h-1.5 w-1.5 rounded-full", s.dot)} />{s.label}</span>;
}

export function HealthDot({ health }: { health: Health }) {
  const m = { up: ["bg-emerald-400", "Up"], degraded: ["bg-amber-400", "Degraded"], down: ["bg-rose-500", "Down"], unknown: ["bg-slate-500", "Unknown"] }[health] ?? ["bg-slate-500", health];
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-slate-500" title={`Health: ${m[1]}`}>
      <span className="relative flex h-2 w-2">{health === "up" && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />}<span className={clsx("relative inline-flex h-2 w-2 rounded-full", m[0])} /></span>{m[1]}
    </span>
  );
}

export function Counter({ value, decimals = 0, suffix = "" }: { value: number; decimals?: number; suffix?: string }) {
  const mv = useMotionValue(0);
  const text = useTransform(mv, (v) => v.toFixed(decimals) + suffix);
  useEffect(() => { const c = animate(mv, value, { duration: 0.9, ease: "easeOut" }); return c.stop; }, [value, mv]);
  return <motion.span>{text}</motion.span>;
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx("h-5 w-5 animate-spin text-violet-700", className)} />;
}

export function Empty({ icon: Icon, title, text, action }: { icon: any; title: string; text?: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 px-6 py-14 text-center">
      <div className="mb-4 rounded-2xl bg-slate-50 p-4"><Icon className="h-7 w-7 text-slate-500" /></div>
      <p className="font-display text-lg font-semibold text-slate-900">{title}</p>
      {text && <p className="mt-1 max-w-md text-sm text-slate-500">{text}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-slate-900/40 p-4 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
          <motion.div role="dialog" aria-modal="true" aria-label={title} className={clsx("my-auto w-full rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl", wide ? "max-w-3xl" : "max-w-lg")} initial={{ scale: 0.94, y: 12 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.94, y: 12 }} onClick={(e) => e.stopPropagation()}>
            <div className="mb-4 flex items-center justify-between"><h3 className="font-display text-lg font-semibold text-slate-900">{title}</h3><button onClick={onClose} aria-label="Close" className="text-slate-500 hover:text-slate-900"><X className="h-5 w-5" /></button></div>
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: React.ReactNode; subtitle?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div><h1 className="font-display text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">{title}</h1>{subtitle && <p className="mt-2 text-sm text-slate-500">{subtitle}</p>}</div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function ErrorBox({ error }: { error: { message: string; hint?: string | null } | null }) {
  if (!error) return null;
  return <div role="alert" className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-700"><p>{error.message}</p>{error.hint && <p className="mt-1 text-xs text-rose-700">{error.hint}</p>}</div>;
}

export const STACK_META: Record<string, { label: string; color: string }> = {
  nextjs: { label: "Next.js", color: "from-slate-200 to-slate-500" },
  wordpress: { label: "WordPress", color: "from-sky-400 to-blue-600" },
  laravel: { label: "Laravel", color: "from-rose-400 to-red-600" },
  static: { label: "Static", color: "from-amber-300 to-orange-500" },
  auto: { label: "AI pick", color: "from-violet-400 to-cyan-400" },
};

export function StackBadge({ stack, ai }: { stack: string; ai?: boolean }) {
  const m = STACK_META[stack] ?? { label: stack, color: "from-slate-300 to-slate-500" };
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-700">
      <span className={clsx("h-2 w-2 rounded-sm bg-gradient-to-br", m.color)} />{m.label}{ai && stack !== "auto" && <span className="text-violet-700">· AI</span>}
    </span>
  );
}
