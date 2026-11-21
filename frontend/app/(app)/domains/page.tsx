"use client";

import { motion } from "framer-motion";
import { Globe2, RefreshCw, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { usePlatformEvents } from "@/components/Shell";
import { useToast } from "@/components/toast";
import { Button, Empty, PageHeader, Spinner } from "@/components/ui";
import { api, timeAgo } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { DomainRecord } from "@/lib/types";

const STATUS: Record<string, { label: string; cls: string; hint?: string }> = {
  quoted: { label: "Quoted", cls: "bg-slate-500/10 text-slate-600 border-slate-500/20", hint: "Price checked, not bought yet" },
  ordering: { label: "Ordering", cls: "bg-violet-500/10 text-violet-700 border-violet-500/30" },
  pending: { label: "Activating", cls: "bg-cyan-500/10 text-cyan-700 border-cyan-500/30", hint: "Order placed, waiting for the registry" },
  active: { label: "Active", cls: "bg-emerald-500/10 text-emerald-700 border-emerald-500/30" },
  failed: { label: "Failed", cls: "bg-rose-500/10 text-rose-700 border-rose-500/30", hint: "Nothing was charged" },
  unknown: { label: "Needs check", cls: "bg-amber-500/10 text-amber-700 border-amber-500/30", hint: "Check the provider dashboard, then Sync or Reset" },
};

export default function DomainsPage() {
  const toast = useToast();
  const { can } = useAuth();
  const [rows, setRows] = useState<DomainRecord[] | null>(null);
  const [busy, setBusy] = useState("");
  const load = useCallback(() => api<DomainRecord[]>("/api/domains").then(setRows).catch(() => setRows([])), []);
  useEffect(() => { load(); }, [load]);
  usePlatformEvents((ev) => { if (ev.type === "domain") load(); });

  const act = async (d: DomainRecord, op: "sync" | "reset") => {
    if (op === "reset" && !confirm(`Confirm that ${d.name} was NOT bought at ${d.provider}. The platform may then try to buy it again.`)) return;
    setBusy(d.id + op);
    try {
      const r = await api<DomainRecord>(`/api/domains/${d.id}/${op}`, { method: "POST" });
      toast({ title: op === "sync" ? `${d.name}: ${STATUS[r.status]?.label ?? r.status}` : `${d.name} reset — resume the website's job to buy it`, level: "success" });
      load();
    } catch (e: any) { toast({ title: "Action failed", message: e.message, level: "error" }); }
    finally { setBusy(""); }
  };

  return (
    <div>
      <PageHeader title="Domains" subtitle="Domains bought through Cloudflare or OVH. Each purchase is recorded so a domain is never ordered twice." />
      {!rows ? <Spinner /> : !rows.length ? (
        <Empty icon={Globe2} title="No domains bought yet" text="Choose Cloudflare or OVH as the domain provider when creating a website, then pick “Buy a new domain”."
          action={<Link href="/new"><Button>Create website</Button></Link>} />
      ) : (
        <div className="glass overflow-x-auto p-0">
          <table className="w-full min-w-[820px] text-sm">
            <thead><tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wider text-slate-500"><th className="p-4">Domain</th><th>Status</th><th>Provider</th><th>Price</th><th>Expires</th><th>Website</th><th /></tr></thead>
            <tbody>
              {rows.map((d, i) => {
                const s = STATUS[d.status] ?? { label: d.status, cls: "bg-slate-500/10 text-slate-600 border-slate-500/20" };
                return (
                  <motion.tr key={d.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: Math.min(i, 20) * 0.02 }} className="border-b border-slate-200 align-top">
                    <td className="p-4"><p className="font-mono text-slate-900">{d.name}</p>{d.error && <p className="mt-1 max-w-xs text-xs text-rose-700">{d.error}</p>}<p className="mt-1 text-[11px] text-slate-500">added {timeAgo(d.created_at)}</p></td>
                    <td className="pt-4"><span className={`inline-flex rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${s.cls}`} title={s.hint}>{s.label}</span>{s.hint && <p className="mt-1 max-w-[180px] text-[11px] text-slate-500">{s.hint}</p>}</td>
                    <td className="pt-4 capitalize text-slate-600">{d.provider}</td>
                    <td className="pt-4 text-slate-600">{d.price != null ? `${d.price.toFixed(2)} ${d.currency ?? ""}` : "—"}<p className="text-[11px] text-slate-500">{d.years}y · auto-renew {d.auto_renew ? "on" : "off"}</p></td>
                    <td className="pt-4 text-xs text-slate-500">{d.expires_at?.slice(0, 10) ?? "—"}</td>
                    <td className="pt-4">{d.website_id ? <Link href={`/sites/${d.website_id}`} className="text-cyan-700 hover:underline">{d.website_name ?? "open"}</Link> : "—"}</td>
                    <td className="pr-4 pt-3 text-right">
                      {can("operator") && d.status !== "active" && <Button size="sm" variant="ghost" loading={busy === d.id + "sync"} onClick={() => act(d, "sync")}><RefreshCw className="h-3.5 w-3.5" /> Sync</Button>}
                      {can("admin") && ["unknown", "failed"].includes(d.status) && <Button size="sm" variant="subtle" className="ml-1" loading={busy === d.id + "reset"} onClick={() => act(d, "reset")}><RotateCcw className="h-3.5 w-3.5" /> Reset</Button>}
                    </td>
                  </motion.tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
