"use client";

import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import { AlertOctagon, ArrowRight, ExternalLink, Globe, Hourglass, Layers, Plus, Rocket, Search, Sparkles, Wand2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { usePlatformEvents } from "@/components/Shell";
import { Button, Counter, Empty, HealthDot, Spinner, StackBadge, StatusBadge } from "@/components/ui";
import { api, timeAgo } from "@/lib/api";
import type { Website } from "@/lib/types";

const FILTERS = [
  { key: "", label: "All" }, { key: "live", label: "Live" }, { key: "preview", label: "Preview" }, { key: "generating", label: "Generating" },
  { key: "awaiting_approval", label: "Approval" }, { key: "failed", label: "Failed" }, { key: "archived", label: "Archived" },
];

export default function Dashboard() {
  const router = useRouter();
  const [sites, setSites] = useState<Website[] | null>(null);
  const [stats, setStats] = useState<any>(null);
  const [filter, setFilter] = useState("");
  const [q, setQ] = useState("");
  const [cmd, setCmd] = useState("");
  const [progress, setProgress] = useState<Record<string, { p: number; step: string }>>({});

  const load = useCallback(async () => {
    const params = new URLSearchParams();
    if (filter) params.set("status", filter);
    if (q) params.set("q", q);
    const [w, s] = await Promise.all([api<{ items: Website[] }>(`/api/websites?${params}`), api("/api/stats")]);
    setSites(w.items);
    setStats(s);
  }, [filter, q]);

  useEffect(() => { const t = setTimeout(() => load().catch(() => setSites([])), q ? 250 : 0); return () => clearTimeout(t); }, [load, q]);

  usePlatformEvents((ev) => {
    if (ev.type === "step_started" || ev.type === "step_completed") setProgress((p) => ({ ...p, [ev.website_id]: { p: ev.progress ?? 0, step: ev.step } }));
    if (["job_completed", "job_failed", "job_started", "approval_required", "job_cancelled", "health"].includes(ev.type)) load().catch(() => {});
  });

  const tiles = [
    { label: "Websites", value: stats?.websites ?? 0, sub: `of ${stats?.capacity ?? 1000} capacity`, icon: Layers, grad: "from-violet-500/30" },
    { label: "Live", value: stats?.by_status?.live ?? 0, sub: `${stats?.health?.up ?? 0} healthy`, icon: Globe, grad: "from-emerald-500/30" },
    { label: "In preview", value: (stats?.by_status?.preview ?? 0) + (stats?.by_status?.generating ?? 0), sub: `${stats?.by_status?.generating ?? 0} building now`, icon: Sparkles, grad: "from-cyan-500/30" },
    { label: "Needs approval", value: stats?.by_status?.awaiting_approval ?? 0, sub: "human-in-the-loop", icon: Hourglass, grad: "from-amber-500/30" },
    { label: "Failed", value: stats?.by_status?.failed ?? 0, sub: "recoverable", icon: AlertOctagon, grad: "from-rose-500/30" },
  ];

  return (
    <div>
      <section className="relative mb-10 overflow-hidden rounded-3xl border border-slate-200 bg-gradient-to-br from-violet-100 via-white to-cyan-50 p-8 sm:p-10">
        <div className="pointer-events-none absolute -right-20 -top-20 h-72 w-72 animate-spinslow rounded-full opacity-30 blur-3xl [animation-duration:20s]" style={{ background: "conic-gradient(#8b5cf6,#22d3ee,#34d399,#f472b6,#8b5cf6)" }} />
        <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="chip mb-4 border-violet-400/30 text-violet-700"><Wand2 className="h-3 w-3" /> 11 AI agents · one command</motion.p>
        <motion.h1 initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="font-display text-4xl font-bold tracking-tight sm:text-5xl">
          Your <span className="text-grad">website factory</span>
        </motion.h1>
        <p className="mt-3 max-w-2xl text-slate-500">Describe a website. The platform plans, designs, writes, builds, tests, deploys and monitors it — independently, at scale.</p>
        <form onSubmit={(e) => { e.preventDefault(); router.push(`/new${cmd ? `?prompt=${encodeURIComponent(cmd)}` : ""}`); }} className="glow-border mt-6 flex max-w-3xl items-center gap-2 rounded-2xl bg-white/90 p-2">
          <Sparkles className="ml-2 h-5 w-5 shrink-0 text-violet-700" />
          <input value={cmd} onChange={(e) => setCmd(e.target.value)} placeholder="Create a website about sustainable living using Next.js…" aria-label="Website instruction"
            className="min-w-0 flex-1 bg-transparent px-2 py-2.5 text-sm text-slate-900 outline-none placeholder:text-slate-500" />
          <Button type="submit">Generate <ArrowRight className="h-4 w-4" /></Button>
        </form>
      </section>

      <div className="mb-10 grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
        {tiles.map((t, i) => (
          <motion.div key={t.label} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}
            className={clsx("glass relative overflow-hidden bg-gradient-to-br to-transparent p-5", t.grad)}>
            <t.icon className="absolute right-4 top-4 h-5 w-5 text-slate-900/30" />
            <p className="text-xs uppercase tracking-wider text-slate-500">{t.label}</p>
            <p className="mt-2 font-display text-4xl font-bold tabular-nums"><Counter value={t.value} /></p>
            <p className="mt-1 text-xs text-slate-500">{t.sub}</p>
          </motion.div>
        ))}
      </div>

      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex flex-wrap gap-1 rounded-xl border border-slate-200 bg-slate-50 p-1">
          {FILTERS.map((f) => (
            <button key={f.key} onClick={() => setFilter(f.key)} className={clsx("relative rounded-lg px-3 py-1.5 text-xs font-medium transition", filter === f.key ? "text-slate-900" : "text-slate-500 hover:text-slate-900")}>
              {filter === f.key && <motion.span layoutId="filter" className="absolute inset-0 rounded-lg bg-slate-100" />}<span className="relative">{f.label}</span>
            </button>
          ))}
        </div>
        <div className="relative sm:ml-auto sm:w-72">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search websites" className="input pl-9" aria-label="Search websites" />
        </div>
      </div>

      {sites === null ? <div className="flex justify-center py-20"><Spinner className="h-8 w-8" /></div>
        : sites.length === 0 ? (
          <Empty icon={Rocket} title="No websites yet" text="Create your first website from a single instruction. It takes about a minute in offline mode."
            action={<Link href="/new"><Button><Plus className="h-4 w-4" /> Create website</Button></Link>} />
        ) : (
          <motion.div layout className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
            <AnimatePresence>
              {sites.map((s, i) => <SiteCard key={s.id} site={s} index={i} live={progress[s.id]} />)}
            </AnimatePresence>
          </motion.div>
        )}
    </div>
  );
}

function SiteCard({ site, index, live }: { site: Website; index: number; live?: { p: number; step: string } }) {
  const p = site.palette;
  const generating = site.status === "generating";
  return (
    <motion.div layout initial={{ opacity: 0, y: 20, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, scale: 0.95 }} transition={{ delay: Math.min(index, 12) * 0.04 }}
      whileHover={{ y: -4 }} className="group">
      <Link href={`/sites/${site.id}`} className={clsx("glass block overflow-hidden transition-shadow hover:shadow-[0_20px_60px_-20px_rgba(139,92,246,.45)]", generating && "glow-border")}>
        <div className="relative h-28 overflow-hidden" style={{ background: p ? `linear-gradient(120deg, ${p.primary}, ${p.secondary} 60%, ${p.accent})` : "linear-gradient(120deg,#1f2340,#11152a)" }}>
          {!p && <div className="absolute inset-0 animate-pulse bg-gradient-to-r from-violet-500/20 via-cyan-500/20 to-emerald-500/20" />}
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_80%_20%,rgba(255,255,255,.35),transparent_40%)] opacity-60 transition group-hover:opacity-90" />
          <div className="absolute bottom-3 left-4 right-4 flex items-end justify-between">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-slate-50 font-display text-lg font-bold text-white backdrop-blur">{site.name[0]}</div>
            <span className="rounded-full bg-black/50 backdrop-blur"><StatusBadge status={site.status} /></span>
          </div>
        </div>
        <div className="p-5">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <h3 className="truncate font-display text-lg font-semibold text-slate-900">{site.name}</h3>
              <p className="mt-0.5 line-clamp-1 text-xs text-slate-500">{site.tagline || site.prompt}</p>
            </div>
            {site.quality_score != null && (
              <div className="shrink-0 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-center" title="Quality score">
                <p className="font-display text-sm font-bold text-slate-900">{site.quality_score}</p><p className="text-[9px] uppercase text-slate-500">QA</p>
              </div>
            )}
          </div>
          {generating && (
            <div className="mt-4">
              <div className="mb-1 flex justify-between text-[11px] text-slate-500"><span>{live?.step ?? "working"}…</span><span>{Math.round(live?.p ?? 0)}%</span></div>
              <div className="relative h-1.5 overflow-hidden rounded-full bg-slate-100">
                <motion.div className="h-full bg-grad" animate={{ width: `${Math.max(5, live?.p ?? 5)}%` }} />
                <div className="absolute inset-y-0 w-1/3 animate-shimmer bg-gradient-to-r from-transparent via-white/40 to-transparent" />
              </div>
            </div>
          )}
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <StackBadge stack={site.stack} ai={site.stack_selected_by === "ai"} />
            <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] text-slate-600">{site.hosting_provider}</span>
            {site.status === "live" && <HealthDot health={site.health_status} />}
          </div>
          <div className="mt-4 flex items-center justify-between border-t border-slate-200 pt-3 text-xs text-slate-500">
            <span>{timeAgo(site.updated_at)}</span>
            {site.live_url && <span className="flex items-center gap-1 text-cyan-700 opacity-0 transition group-hover:opacity-100">{site.domain || "open"} <ExternalLink className="h-3 w-3" /></span>}
          </div>
        </div>
      </Link>
    </motion.div>
  );
}
