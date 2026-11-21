"use client";

import clsx from "clsx";
import { TerminalSquare } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { JobEvent } from "@/lib/types";

const TYPE_STYLE: Record<string, string> = {
  step_started: "text-violet-300", step_completed: "text-emerald-300", step_failed: "text-rose-300", step_error: "text-rose-300",
  step_retry: "text-amber-300", approval_required: "text-amber-300", job_completed: "text-emerald-300 font-semibold",
  job_failed: "text-rose-300 font-semibold", job_started: "text-cyan-300", job_resumed: "text-cyan-300", rollback: "text-amber-300",
};
const LEVEL_STYLE: Record<string, string> = { info: "text-slate-300", success: "text-emerald-300", warning: "text-amber-300", error: "text-rose-300" };

export function Terminal({ events, connected, live }: { events: JobEvent[]; connected: boolean; live: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const [stick, setStick] = useState(true);
  useEffect(() => { if (stick && ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, [events, stick]);

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-white/[0.08] bg-[#04050a]/90 shadow-2xl shadow-black/40">
      <div className="flex items-center gap-2 border-b border-white/[0.06] px-4 py-2.5">
        <span className="h-2.5 w-2.5 rounded-full bg-rose-500/80" /><span className="h-2.5 w-2.5 rounded-full bg-amber-400/80" /><span className="h-2.5 w-2.5 rounded-full bg-emerald-400/80" />
        <TerminalSquare className="ml-2 h-3.5 w-3.5 text-slate-500" />
        <span className="font-mono text-[11px] text-slate-400">agent-stream</span>
        <span className="ml-auto flex items-center gap-1.5 font-mono text-[10px] text-slate-500">
          <span className={clsx("h-1.5 w-1.5 rounded-full", connected ? "bg-emerald-400" : "bg-amber-400 animate-pulse")} />
          {connected ? (live ? "LIVE" : "CONNECTED") : "RECONNECTING"}
        </span>
      </div>
      <div ref={ref} onScroll={(e) => { const el = e.currentTarget; setStick(el.scrollHeight - el.scrollTop - el.clientHeight < 40); }}
        className="flex-1 overflow-y-auto px-4 py-3 font-mono text-[11.5px] leading-relaxed" role="log" aria-live="off">
        {events.length === 0 && <p className="text-slate-600">Waiting for the orchestrator…</p>}
        {events.map((e, i) => {
          const t = new Date(e.ts);
          const style = TYPE_STYLE[e.type] ?? LEVEL_STYLE[e.level] ?? "text-slate-300";
          const prefix = e.type === "log" ? "" : `[${e.type.replace(/_/g, " ")}] `;
          return (
            <div key={e.id != null ? `e${e.id}` : `x${i}`} className="flex gap-2 py-[1px]">
              <span className="shrink-0 text-slate-600">{isNaN(t.getTime()) ? "" : t.toLocaleTimeString([], { hour12: false })}</span>
              {e.step && <span className="w-[86px] shrink-0 truncate text-cyan-500/70">{e.step}</span>}
              <span className={clsx("min-w-0 break-words", style)}>{prefix}{e.message}</span>
            </div>
          );
        })}
        {live && <span className="inline-block h-3.5 w-2 animate-blink bg-violet-400 align-middle" />}
      </div>
    </div>
  );
}
