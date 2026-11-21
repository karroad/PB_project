"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Check, ClipboardCheck, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { usePlatformEvents } from "@/components/Shell";
import { useToast } from "@/components/toast";
import { Button, Empty, PageHeader, Spinner, StatusBadge } from "@/components/ui";
import { api, timeAgo } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Approval } from "@/lib/types";

const ACTION_LABEL: Record<string, string> = { publish: "Publish website", provision_hosting: "Provision hosting", configure_dns: "Change DNS records", register_domain: "Register domain" };

export default function ApprovalsPage() {
  const toast = useToast();
  const { can } = useAuth();
  const [rows, setRows] = useState<Approval[] | null>(null);
  const [status, setStatus] = useState("pending");
  const [comment, setComment] = useState<Record<string, string>>({});
  const load = useCallback(() => api<Approval[]>(`/api/approvals?status=${status}`).then(setRows), [status]);
  useEffect(() => { load(); }, [load]);
  usePlatformEvents((ev) => { if (ev.type === "approval_required" || ev.type?.startsWith("approval_")) load(); });

  const decide = async (a: Approval, d: "approve" | "reject") => {
    try {
      await api(`/api/approvals/${a.id}/${d}`, { method: "POST", json: { comment: comment[a.id] || null } });
      toast({ title: d === "approve" ? "Approved — job resumed" : "Rejected", level: d === "approve" ? "success" : "warning" });
      load();
    } catch (e: any) { toast({ title: "Decision failed", message: e.message, level: "error" }); }
  };

  return (
    <div>
      <PageHeader title="Approvals" subtitle="Infrastructure changes, DNS, purchases and publishing wait here for a human decision."
        actions={<select className="input w-40" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter">{["pending", "approved", "rejected", "all"].map((s) => <option key={s}>{s}</option>)}</select>} />
      {!rows ? <Spinner /> : !rows.length ? <Empty icon={ClipboardCheck} title="Nothing waiting" text="Agents never change external accounts or publish without approval where it's required." /> : (
        <div className="grid gap-4 lg:grid-cols-2">
          <AnimatePresence>
            {rows.map((a) => (
              <motion.div key={a.id} layout initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.95 }} className={`glass p-5 ${a.status === "pending" ? "glow-border" : ""}`}>
                <div className="flex items-center gap-2"><StatusBadge status={a.status} /><span className="text-xs text-slate-500">{timeAgo(a.requested_at)}</span></div>
                <h3 className="mt-3 font-display text-lg font-semibold">{ACTION_LABEL[a.action] ?? a.action}</h3>
                <p className="text-sm text-slate-600">{a.description}</p>
                <Link href={`/sites/${a.website_id}`} className="mt-1 inline-block text-xs text-cyan-700 hover:underline">{a.website_name}</Link>
                {a.details && Object.keys(a.details).length > 0 && <pre className="mt-3 max-h-40 overflow-auto rounded-lg bg-slate-50 p-3 font-mono text-[11px] text-slate-500">{JSON.stringify(a.details, null, 2)}</pre>}
                {a.status === "pending" && can("operator") && (
                  <div className="mt-4 space-y-2">
                    <input className="input" placeholder="Comment (optional)" value={comment[a.id] ?? ""} onChange={(e) => setComment({ ...comment, [a.id]: e.target.value })} />
                    <div className="flex gap-2"><Button onClick={() => decide(a, "approve")}><Check className="h-4 w-4" /> Approve</Button><Button variant="danger" onClick={() => decide(a, "reject")}><X className="h-4 w-4" /> Reject</Button></div>
                    {["provision_hosting", "configure_dns", "register_domain"].includes(a.action) && !can("admin") && <p className="text-xs text-amber-700">Only admins can approve infrastructure changes.</p>}
                  </div>
                )}
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}
