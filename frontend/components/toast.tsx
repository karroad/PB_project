"use client";

import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import Link from "next/link";
import { createContext, useCallback, useContext, useState } from "react";

type Level = "info" | "success" | "warning" | "error";
interface Toast { id: number; title: string; message?: string; level: Level; link?: string | null }
const Ctx = createContext<(t: Omit<Toast, "id">) => void>(() => {});
let seq = 0;

const STYLE: Record<Level, { icon: any; ring: string; color: string }> = {
  info: { icon: Info, ring: "from-indigo-500/40", color: "text-indigo-700" },
  success: { icon: CheckCircle2, ring: "from-emerald-500/40", color: "text-emerald-700" },
  warning: { icon: AlertTriangle, ring: "from-amber-500/40", color: "text-amber-700" },
  error: { icon: XCircle, ring: "from-rose-500/50", color: "text-rose-700" },
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dismiss = (id: number) => setToasts((t) => t.filter((x) => x.id !== id));
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = ++seq;
    setToasts((all) => [...all.slice(-4), { ...t, id }]);
    setTimeout(() => dismiss(id), t.level === "error" ? 9000 : 5000);
  }, []);

  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-[min(380px,calc(100vw-32px))] flex-col gap-2" aria-live="polite">
        <AnimatePresence initial={false}>
          {toasts.map((t) => {
            const s = STYLE[t.level];
            const Icon = s.icon;
            return (
              <motion.div key={t.id} layout initial={{ opacity: 0, x: 60, scale: 0.95 }} animate={{ opacity: 1, x: 0, scale: 1 }} exit={{ opacity: 0, x: 60, scale: 0.95 }}
                transition={{ type: "spring", stiffness: 380, damping: 30 }}
                className={`pointer-events-auto rounded-2xl bg-gradient-to-br ${s.ring} to-transparent p-px shadow-2xl shadow-slate-900/10`}>
                <div className="flex gap-3 rounded-2xl bg-white/90 p-3.5 backdrop-blur-xl">
                  <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${s.color}`} />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-slate-900">{t.title}</p>
                    {t.message && <p className="mt-0.5 line-clamp-3 text-xs text-slate-500">{t.message}</p>}
                    {t.link && <Link href={t.link} className="mt-1 inline-block text-xs text-cyan-700 hover:underline">Open →</Link>}
                  </div>
                  <button onClick={() => dismiss(t.id)} className="text-slate-500 hover:text-slate-900" aria-label="Dismiss"><X className="h-4 w-4" /></button>
                </div>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </Ctx.Provider>
  );
}

export const useToast = () => useContext(Ctx);
