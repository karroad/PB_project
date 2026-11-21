"use client";

import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import { Ban, Clock, Cpu, ExternalLink, Layers, PartyPopper, RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button, Spinner, StatusBadge } from "../ui";
import { useToast } from "../toast";
import { Celebration } from "./Celebration";
import { ProgressOrb } from "./ProgressOrb";
import { STEP_ICONS, StepCard } from "./StepCard";
import { Terminal } from "./Terminal";
import { usePipeline } from "./usePipeline";

function elapsed(start?: string | null, end?: string | null) {
  if (!start) return "0:00";
  const fix = (s: string) => new Date(s.includes("+") || s.endsWith("Z") ? s : s + "Z");
  const sec = Math.max(0, Math.floor(((end ? fix(end) : new Date()).getTime() - fix(start).getTime()) / 1000));
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}

export function PipelineView({ jobId, onFinished, liveUrl, previewUrl, onPublish, onRequestChanges }: {
  jobId: string; onFinished?: (status: string) => void; liveUrl?: string | null; previewUrl?: string | null;
  onPublish?: () => void; onRequestChanges?: () => void;
}) {
  const toast = useToast();
  const { can } = useAuth();
  const [celebrate, setCelebrate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [, tick] = useState(0);
  const { job, events, approval, connected, error, reload } = usePipelineWithToasts(jobId, toast, (s) => {
    if (s === "completed") { setCelebrate(true); setTimeout(() => setCelebrate(false), 2600); }
    onFinished?.(s);
  });

  const running = job?.status === "running" || job?.status === "queued";
  useEffect(() => { if (!running) return; const t = setInterval(() => tick((x) => x + 1), 1000); return () => clearInterval(t); }, [running]);

  const steps = job?.steps ?? [];
  const isPreview = ["generate", "revise", "regenerate_content"].includes(job?.type ?? "");
  const current = steps.find((s) => ["running", "retrying", "waiting", "failed"].includes(s.status)) ?? null;
  const done = steps.filter((s) => s.status === "completed").length;
  const label = useMemo(() => {
    if (!job) return "";
    if (job.status === "completed") return isPreview ? "Preview ready" : "Website live";
    if (job.status === "failed") return "Needs attention";
    if (job.status === "awaiting_approval") return "Awaiting approval";
    if (job.status === "queued") return "Queued";
    if (job.status === "cancelled") return "Cancelled";
    return current?.agent ?? "Starting";
  }, [job, current]);

  const act = async (fn: () => Promise<any>, ok?: string) => {
    setBusy(true);
    try { await fn(); if (ok) toast({ title: ok, level: "success" }); await reload(); }
    catch (e: any) { toast({ title: "Action failed", message: e.message, level: "error" }); }
    finally { setBusy(false); }
  };

  if (error) return <p className="text-rose-700">{error}</p>;
  if (!job) return <div className="flex justify-center py-20"><Spinner className="h-8 w-8" /></div>;
  const CurIcon = current ? STEP_ICONS[current.key] ?? Sparkles : Sparkles;

  return (
    <div className="space-y-6">
      {celebrate && <Celebration />}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
        <div className="glass relative flex flex-col items-center overflow-hidden p-6">
          <ProgressOrb progress={job.progress} status={job.status} steps={steps} label={label} />
          <p className="mt-4 text-xs text-slate-500">{done} of {steps.length} agents complete</p>
        </div>

        <div className="glass flex flex-col p-6">
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge status={job.status} />
            <span className="rounded-md bg-slate-100 px-2 py-0.5 font-mono text-[11px] text-slate-500">{job.type}</span>
            <span className="flex items-center gap-1.5 text-xs text-slate-500"><Clock className="h-3.5 w-3.5" /> <span className="tabular-nums">{elapsed(job.started_at, running ? null : job.finished_at)}</span></span>
            {job.attempts > 1 && <span className="text-xs text-amber-700">attempt {job.attempts}</span>}
            {job.worker_id && <span className="hidden items-center gap-1 text-[11px] text-slate-500 md:flex"><Cpu className="h-3 w-3" />{job.worker_id}</span>}
          </div>

          <AnimatePresence mode="wait">
            <motion.div key={job.status + (current?.key ?? "")} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="mt-6 flex items-start gap-4">
              <div className={clsx("grid h-14 w-14 shrink-0 place-items-center rounded-2xl",
                job.status === "completed" ? "bg-emerald-500/15 text-emerald-700" : job.status === "failed" ? "bg-rose-500/15 text-rose-700" : "bg-grad text-white shadow-lg shadow-violet-600/30")}>
                {job.status === "completed" ? <PartyPopper className="h-7 w-7" /> : <CurIcon className="h-7 w-7" />}
              </div>
              <div className="min-w-0">
                <p className="text-xs uppercase tracking-[0.16em] text-slate-500">{job.status === "completed" ? "Done" : job.status === "failed" ? "Stopped at" : "Now working"}</p>
                <h2 className="font-display text-2xl font-bold text-slate-900">
                  {job.status === "completed" ? (isPreview ? "Your preview is ready 👀" : "Your website is live 🎉") : current ? current.name : job.status === "queued" ? "Waiting for a free worker…" : "Preparing"}
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  {job.status === "completed" ? (isPreview ? "Review it, request changes if needed, then publish when you're happy." : "Deployed, verified and registered for monitoring.")
                    : job.status === "failed" ? job.error : current?.logs?.at(-1)?.message ?? "The orchestrator is scheduling agents."}
                </p>
              </div>
            </motion.div>
          </AnimatePresence>

          {/* mini agent rail */}
          <div className="mt-6 flex flex-wrap gap-1.5">
            {steps.map((s) => {
              const I = STEP_ICONS[s.key] ?? Layers;
              return (
                <motion.div key={s.key} title={s.name} layout
                  className={clsx("grid h-8 w-8 place-items-center rounded-lg border transition-colors duration-500",
                    s.status === "completed" && "border-emerald-500/30 bg-emerald-500/15 text-emerald-700",
                    (s.status === "running" || s.status === "retrying") && "border-violet-400/50 bg-violet-500/20 text-slate-900",
                    s.status === "pending" && "border-slate-200 bg-slate-50 text-slate-600",
                    s.status === "failed" && "border-rose-500/40 bg-rose-500/15 text-rose-700",
                    s.status === "waiting" && "border-amber-400/40 bg-amber-500/15 text-amber-700")}
                  animate={s.status === "running" ? { y: [0, -3, 0] } : { y: 0 }} transition={s.status === "running" ? { duration: 1, repeat: Infinity } : {}}>
                  <I className="h-4 w-4" />
                </motion.div>
              );
            })}
          </div>

          <div className="mt-auto flex flex-wrap gap-2 pt-6">
            {job.status === "completed" && isPreview && previewUrl && (
              <a href={previewUrl} target="_blank" rel="noreferrer"><Button variant="ghost"><ExternalLink className="h-4 w-4" /> Open preview</Button></a>
            )}
            {job.status === "completed" && isPreview && onRequestChanges && <Button variant="ghost" onClick={onRequestChanges}>Request changes</Button>}
            {job.status === "completed" && isPreview && onPublish && <Button onClick={onPublish}>Publish</Button>}
            {job.status === "completed" && !isPreview && liveUrl && (
              <a href={liveUrl} target="_blank" rel="noreferrer"><Button><ExternalLink className="h-4 w-4" /> Open live website</Button></a>
            )}
            {(job.status === "failed" || job.status === "cancelled") && can("operator") && (
              <Button onClick={() => act(() => api(`/api/jobs/${job.id}/retry`, { method: "POST" }), "Job resumed")} loading={busy}><RefreshCw className="h-4 w-4" /> Resume job</Button>
            )}
            {["running", "queued", "awaiting_approval"].includes(job.status) && can("operator") && (
              <Button variant="ghost" onClick={() => act(() => api(`/api/jobs/${job.id}/cancel`, { method: "POST" }), "Cancellation requested")} disabled={busy}><Ban className="h-4 w-4" /> Cancel</Button>
            )}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <ol className="relative min-w-0">
          {steps.map((s, i) => (
            <StepCard key={s.key} step={s} index={i} last={i === steps.length - 1} busy={busy}
              approval={s.status === "waiting" ? approval : null}
              onApprove={approval && can("operator") ? () => act(() => api(`/api/approvals/${approval.id}/approve`, { method: "POST", json: {} }), "Approved — resuming") : undefined}
              onReject={approval && can("operator") ? () => act(() => api(`/api/approvals/${approval.id}/reject`, { method: "POST", json: {} }), "Rejected") : undefined}
              onRetry={s.status === "failed" && can("operator") ? () => act(() => api(`/api/jobs/${job.id}/retry`, { method: "POST" }), "Retrying") : undefined} />
          ))}
        </ol>
        <div className="xl:sticky xl:top-24 xl:h-[calc(100vh-8rem)]">
          <div className="h-[420px] xl:h-full"><Terminal events={events} connected={connected} live={!!running} /></div>
        </div>
      </div>
    </div>
  );
}


function usePipelineWithToasts(jobId: string, toast: ReturnType<typeof useToast>, onFinished: (s: string) => void) {
  return usePipeline(jobId, {
    onStepCompleted: (s) => toast({ title: `✓ ${s.name}`, level: "success" }),
    onFinished,
  });
}
