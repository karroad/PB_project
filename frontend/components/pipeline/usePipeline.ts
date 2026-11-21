"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, sseUrl } from "@/lib/api";
import type { Approval, Job, JobEvent, JobStep } from "@/lib/types";

const MAX_TERMINAL = 600;

/** Loads a job, replays its persisted event history and then follows the live SSE stream. */
export function usePipeline(jobId: string | null, handlers: { onStepCompleted?: (s: JobStep) => void; onFinished?: (status: string) => void } = {}) {
  const [job, setJob] = useState<Job | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const h = useRef(handlers);
  h.current = handlers;
  const lastId = useRef(0);
  const live = useRef(false); // false while replaying history, so old events don't re-trigger toasts
  const jobRef = useRef<Job | null>(null);
  jobRef.current = job;

  const reload = useCallback(async () => {
    if (!jobId) return;
    const j = await api<Job>(`/api/jobs/${jobId}`);
    setJob(j);
    setApproval(j.approvals?.find((a) => a.status === "pending") ?? null);
    return j;
  }, [jobId]);

  const apply = useCallback((ev: JobEvent) => {
    if (ev.id) {
      if (ev.id <= lastId.current) return;
      lastId.current = ev.id;
    }
    if (ev.type !== "progress") setEvents((e) => (e.length >= MAX_TERMINAL ? [...e.slice(-MAX_TERMINAL + 1), ev] : [...e, ev]));
    setJob((prev) => {
      if (!prev) return prev;
      const j: Job = { ...prev, steps: prev.steps?.map((s) => ({ ...s })) };
      if (typeof ev.progress === "number") j.progress = ev.progress;
      const st = j.steps?.find((s) => s.key === ev.step);
      switch (ev.type) {
        case "job_started": case "job_resumed": j.status = "running"; break;
        case "step_started": if (st) { st.status = "running"; st.error = null; st.started_at = ev.ts; st.attempts = ev.data?.attempt ?? st.attempts; } j.current_step = ev.step; j.status = "running"; break;
        case "log":
          if (st) {
            st.logs = [...(st.logs || []), { ts: ev.ts, level: ev.level as any, message: ev.message }].slice(-300);
            if (ev.data?.step_progress != null) st.progress = ev.data.step_progress;
          }
          break;
        case "progress": if (st && ev.data?.step_progress != null) st.progress = ev.data.step_progress; break;
        case "step_retry": if (st) st.status = "retrying"; break;
        case "step_completed":
          if (st) {
            st.status = "completed"; st.progress = 100; st.output = ev.data?.output ?? st.output; st.finished_at = ev.ts;
          }
          break;
        case "step_failed": if (st) { st.status = "failed"; st.error = ev.message; st.output = { ...st.output, error: ev.data }; st.finished_at = ev.ts; } break;
        case "approval_required":
          if (st) st.status = "waiting";
          j.status = "awaiting_approval";
          break;
        case "approval_approved": case "approval_rejected": j.status = "queued"; break;
        case "job_completed": j.status = "completed"; j.progress = 100; j.finished_at = ev.ts; break;
        case "job_failed": j.status = "failed"; j.error = ev.message; j.finished_at = ev.ts; break;
        case "job_cancelled": j.status = "cancelled"; j.finished_at = ev.ts; break;
      }
      return j;
    });
    // side effects live outside the state updater (StrictMode may run updaters twice)
    if (!live.current) return;
    if (ev.type === "step_completed") {
      const name = jobRef.current?.steps?.find((s) => s.key === ev.step)?.name ?? ev.step ?? "";
      h.current.onStepCompleted?.({ key: ev.step, name, output: ev.data?.output } as JobStep);
    } else if (ev.type === "approval_required") {
      setApproval({ id: ev.data?.approval_id, job_id: ev.job_id, website_id: ev.website_id, step_key: ev.step || "", action: ev.data?.action, description: ev.message, details: ev.data?.details, status: "pending", requested_at: ev.ts, decided_at: null });
    } else if (ev.type === "approval_approved" || ev.type === "approval_rejected") {
      setApproval(null);
    } else if (ev.type.startsWith("job_") && ["job_completed", "job_failed", "job_cancelled"].includes(ev.type)) {
      h.current.onFinished?.(ev.type.slice(4));
    }
  }, []);

  useEffect(() => {
    if (!jobId) return;
    let es: EventSource | null = null;
    let cancelled = false;
    let retry: ReturnType<typeof setTimeout>;
    lastId.current = 0;
    live.current = false;
    setEvents([]);

    (async () => {
      try {
        const j = await reload();
        if (!j || cancelled) return;
        const history = await api<JobEvent[]>(`/api/jobs/${jobId}/history?after=${Math.max(0, (j.last_event_id ?? 0) - 400)}&limit=400`);
        // Events up to the snapshot are already reflected in `j`: show them in the terminal only.
        const snap = j.last_event_id ?? 0;
        setEvents(history.filter((e) => e.type !== "progress" && (e.id ?? 0) <= snap));
        lastId.current = snap;
        // Events that happened between the snapshot and the history fetch must also update step state
        // (live.current is still false, so this replays silently: no toasts).
        for (const ev of history) if ((ev.id ?? 0) > snap) apply(ev);
        const connect = () => {
          live.current = true;
          es = new EventSource(sseUrl(`/api/jobs/${jobId}/events`, { after: lastId.current }));
          es.onopen = () => setConnected(true);
          es.onmessage = (m) => apply(JSON.parse(m.data));
          es.onerror = () => {
            setConnected(false);
            es?.close();
            if (!cancelled) retry = setTimeout(async () => { await reload().catch(() => {}); connect(); }, 2500);
          };
        };
        connect();
      } catch (e: any) {
        setError(e.message);
      }
    })();
    return () => { cancelled = true; clearTimeout(retry); es?.close(); };
  }, [jobId, reload, apply]);

  return { job, events, approval, connected, error, reload };
}
