"use client";

import { motion } from "framer-motion";
import { Activity, Bot, Cpu, Database, HardDrive, Image as ImageIcon, MemoryStick, Radio, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { usePlatformEvents } from "@/components/Shell";
import { useToast } from "@/components/toast";
import { Button, Card, Empty, HealthDot, PageHeader, Spinner } from "@/components/ui";
import { api, timeAgo } from "@/lib/api";

function Meter({ label, value, icon: Icon, detail }: { label: string; value: number; icon: any; detail?: string }) {
  const state = value >= 90 ? { c: "#f43f5e", t: "Critical" } : value >= 75 ? { c: "#fbbf24", t: "High" } : { c: "#34d399", t: "Normal" };
  return (
    <Card>
      <div className="flex items-center justify-between"><p className="flex items-center gap-2 text-xs uppercase tracking-wider text-slate-500"><Icon className="h-4 w-4" />{label}</p><span className="text-[11px]" style={{ color: state.c }}>● {state.t}</span></div>
      <p className="mt-2 font-display text-3xl font-bold tabular-nums">{value.toFixed(0)}%</p>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100"><motion.div className="h-full rounded-full" style={{ background: state.c }} initial={{ width: 0 }} animate={{ width: `${value}%` }} transition={{ duration: 0.8 }} /></div>
      {detail && <p className="mt-2 text-xs text-slate-500">{detail}</p>}
    </Card>
  );
}

export default function MonitoringPage() {
  const toast = useToast();
  const [d, setD] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api("/api/monitoring/overview").then(setD), []);
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);
  usePlatformEvents((ev) => { if (ev.type === "health") setD((x: any) => x && { ...x, sites: x.sites.map((s: any) => (s.id === ev.website_id ? { ...s, health: ev.health, last_checked_at: new Date().toISOString() } : s)) }); });

  const checkNow = async () => { setBusy(true); try { const r = await api("/api/monitoring/check-now", { method: "POST" }); toast({ title: `Checked ${r.checked} sites`, level: "success" }); load(); } finally { setBusy(false); } };
  if (!d) return <Spinner />;
  const s = d.system;
  return (
    <div>
      <PageHeader title="Monitoring" subtitle="Uptime, SSL and domain expiry, server resources and the orchestration queue." actions={<Button variant="ghost" onClick={checkNow} loading={busy}><RefreshCw className="h-4 w-4" /> Check all now</Button>} />
      <div className="grid gap-4 md:grid-cols-3">
        <Meter label="CPU" value={s.cpu_percent} icon={Cpu} />
        <Meter label="Memory" value={s.memory_percent} icon={MemoryStick} detail={`${s.memory_used_gb} / ${s.memory_total_gb} GB`} />
        <Meter label="Disk" value={s.disk_percent} icon={HardDrive} detail={`${s.disk_free_gb} GB free`} />
      </div>
      <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          { icon: Database, label: "Job queue", value: `${d.queue.queued} queued`, sub: `${d.queue.backend} backend · ${d.queue.running_here}/${d.queue.workers_in_this_process} slots busy` },
          { icon: Radio, label: "Event bus", value: d.event_bus.replace("Bus", ""), sub: "SSE fan-out to dashboards" },
          { icon: Bot, label: "AI text provider", value: d.ai_provider, sub: d.ai_provider === "offline" ? "Set ANTHROPIC_API_KEY for AI copy" : "Claude via Anthropic SDK" },
          { icon: ImageIcon, label: "Image provider", value: d.image_provider, sub: d.image_provider === "fal" ? "Fal.ai connected" : "Add a Fal.ai key for photos" },
        ].map((x) => (
          <Card key={x.label}><p className="flex items-center gap-2 text-xs uppercase tracking-wider text-slate-500"><x.icon className="h-4 w-4" />{x.label}</p><p className="mt-2 font-display text-xl font-semibold capitalize">{x.value}</p><p className="text-xs text-slate-500">{x.sub}</p></Card>
        ))}
      </div>
      <h2 className="mb-3 mt-10 font-display text-lg font-semibold">Live websites <span className="text-sm font-normal text-slate-500">· {d.failed_jobs} failed jobs</span></h2>
      {!d.sites.length ? <Empty icon={Activity} title="No live websites yet" /> : (
        <div className="glass overflow-x-auto p-0">
          <table className="w-full min-w-[700px] text-sm">
            <thead><tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wider text-slate-500"><th className="p-4">Website</th><th>Health</th><th>Hosting</th><th>QA</th><th>SSL expiry</th><th>Failures</th><th>Last check</th></tr></thead>
            <tbody>{d.sites.map((x: any) => (
              <tr key={x.id} className="border-b border-slate-200">
                <td className="p-4"><Link href={`/sites/${x.id}`} className="font-medium text-slate-900 hover:text-cyan-700">{x.name}</Link><p className="max-w-xs truncate font-mono text-[11px] text-slate-500">{x.url}</p></td>
                <td><HealthDot health={x.health} /></td><td className="text-xs text-slate-500">{x.hosting}</td><td className="text-xs">{x.quality ?? "—"}</td>
                <td className="text-xs text-slate-500">{x.monitoring?.ssl_expires_at?.slice(0, 10) ?? "—"}</td><td className="text-xs">{x.monitoring?.consecutive_failures ?? 0}</td>
                <td className="text-xs text-slate-500">{timeAgo(x.last_checked_at)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
