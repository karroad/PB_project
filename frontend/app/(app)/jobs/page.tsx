"use client";

import { motion } from "framer-motion";
import { Ban, ListChecks, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { usePlatformEvents } from "@/components/Shell";
import { useToast } from "@/components/toast";
import { Button, Empty, PageHeader, Spinner, StatusBadge } from "@/components/ui";
import { api, timeAgo } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Job } from "@/lib/types";

export default function JobsPage() {
  const toast = useToast();
  const { can } = useAuth();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [status, setStatus] = useState("");
  const load = useCallback(() => api<Job[]>(`/api/jobs${status ? `?status=${status}` : ""}`).then(setJobs).catch(() => setJobs([])), [status]);
  useEffect(() => { load(); }, [load]);
  usePlatformEvents((ev) => {
    if (ev.type?.startsWith("job_") || ev.type === "step_completed") {
      setJobs((js) => js?.map((j) => (j.id === ev.job_id ? { ...j, progress: ev.progress ?? j.progress, current_step: ev.step ?? j.current_step } : j)) ?? js);
      if (ev.type.startsWith("job_")) load();
    }
  });
  const act = async (j: Job, op: "retry" | "cancel") => {
    try { await api(`/api/jobs/${j.id}/${op}`, { method: "POST" }); toast({ title: op === "retry" ? "Job resumed" : "Cancellation requested", level: "success" }); load(); }
    catch (e: any) { toast({ title: "Failed", message: e.message, level: "error" }); }
  };

  return (
    <div>
      <PageHeader title="Jobs" subtitle="Every generation, redeploy and recovery run — persisted step by step."
        actions={<select className="input w-44" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter status">
          {["", "queued", "running", "awaiting_approval", "completed", "failed", "cancelled"].map((s) => <option key={s} value={s}>{s || "All statuses"}</option>)}
        </select>} />
      {!jobs ? <Spinner /> : !jobs.length ? <Empty icon={ListChecks} title="No jobs" /> : (
        <div className="glass overflow-x-auto p-0">
          <table className="w-full min-w-[760px] text-sm">
            <thead><tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wider text-slate-500"><th className="p-4">Website</th><th>Type</th><th>Status</th><th className="w-56">Progress</th><th>Started</th><th>Attempts</th><th /></tr></thead>
            <tbody>
              {jobs.map((j, i) => (
                <motion.tr key={j.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: Math.min(i, 20) * 0.02 }} className="border-b border-slate-200 hover:bg-slate-50">
                  <td className="p-4"><Link href={`/sites/${j.website_id}`} className="font-medium text-slate-900 hover:text-cyan-700">{j.website_name}</Link>{j.error && <p className="max-w-xs truncate text-xs text-rose-700">{j.error}</p>}</td>
                  <td className="font-mono text-xs text-slate-500">{j.type}</td>
                  <td><StatusBadge status={j.status} /></td>
                  <td className="pr-6"><div className="flex items-center gap-2"><div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100"><motion.div className="h-full bg-grad" animate={{ width: `${j.progress}%` }} /></div><span className="w-10 text-right text-xs tabular-nums text-slate-500">{Math.round(j.progress)}%</span></div>
                    {j.current_step && j.status !== "completed" && <p className="mt-1 text-[11px] text-slate-500">{j.current_step}</p>}</td>
                  <td className="text-xs text-slate-500">{timeAgo(j.started_at || j.created_at)}</td>
                  <td className="text-xs text-slate-500">{j.attempts}</td>
                  <td className="pr-4 text-right">{can("operator") && (["failed", "cancelled"].includes(j.status)
                    ? <Button size="sm" variant="ghost" onClick={() => act(j, "retry")}><RefreshCw className="h-3.5 w-3.5" /> Resume</Button>
                    : ["queued", "running", "awaiting_approval"].includes(j.status) ? <Button size="sm" variant="subtle" onClick={() => act(j, "cancel")}><Ban className="h-3.5 w-3.5" /></Button> : null)}</td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
