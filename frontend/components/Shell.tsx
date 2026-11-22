"use client";

import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity, Bell, CheckCheck, ClipboardCheck, Cpu, Globe2, KeyRound, Server as ServerIcon, LayoutGrid, ListChecks, LogOut, Menu, Plus, ScrollText, Sparkles, Users, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, sseUrl, timeAgo } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Notification } from "@/lib/types";
import { useToast } from "./toast";
import { Spinner } from "./ui";

const NAV = [
  { href: "/", label: "Websites", icon: LayoutGrid },
  { href: "/new", label: "Create website", icon: Plus },
  { href: "/jobs", label: "Jobs", icon: ListChecks },
  { href: "/domains", label: "Domains", icon: Globe2 },
  { href: "/servers", label: "Servers", icon: ServerIcon, role: "operator" as const },
  { href: "/approvals", label: "Approvals", icon: ClipboardCheck },
  { href: "/monitoring", label: "Monitoring", icon: Activity },
  { href: "/providers", label: "Providers", icon: KeyRound, role: "operator" as const },
  { href: "/users", label: "Users", icon: Users, role: "admin" as const },
  { href: "/audit", label: "Audit log", icon: ScrollText, role: "admin" as const },
];

type Listener = (ev: any) => void;
const EventsCtx = createContext<(fn: Listener) => () => void>(() => () => {});
export const usePlatformEvents = (fn: Listener) => {
  const sub = useContext(EventsCtx);
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => sub((e) => ref.current(e)), [sub]);
};

export function Shell({ children }: { children: React.ReactNode }) {
  const { user, loading, logout, can } = useAuth();
  const router = useRouter();
  const path = usePathname();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [bell, setBell] = useState(false);
  const [notes, setNotes] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const [connected, setConnected] = useState(false);
  const [sandbox, setSandbox] = useState(false);
  const listeners = useRef(new Set<Listener>());

  useEffect(() => { if (!loading && !user) router.replace("/login"); }, [loading, user, router]);
  useEffect(() => setOpen(false), [path]);

  const loadNotes = useCallback(() => api<{ unread: number; items: Notification[] }>("/api/notifications?limit=20").then((r) => { setNotes(r.items); setUnread(r.unread); }).catch(() => {}), []);

  useEffect(() => {
    if (!user) return;
    loadNotes();
    api<{ sandbox?: boolean }>("/api/health").then((h) => setSandbox(!!h.sandbox)).catch(() => {});
    let es: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout>;
    const connect = () => {
      es = new EventSource(sseUrl("/api/events"));
      es.onopen = () => setConnected(true);
      es.onerror = () => { setConnected(false); es?.close(); retry = setTimeout(connect, 3000); };
      es.onmessage = (m) => {
        const ev = JSON.parse(m.data);
        if (ev.type === "notification") {
          const n = ev.notification as Notification;
          setNotes((x) => [n, ...x.filter((o) => o.id !== n.id)].slice(0, 30));
          setUnread((u) => u + 1);
          toast({ title: n.title, message: n.message, level: n.level, link: n.link });
        }
        listeners.current.forEach((fn) => fn(ev));
      };
    };
    connect();
    return () => { clearTimeout(retry); es?.close(); };
  }, [user, toast, loadNotes]);

  const subscribe = useCallback((fn: Listener) => { listeners.current.add(fn); return () => { listeners.current.delete(fn); }; }, []);

  const markAll = async () => { await api("/api/notifications/read", { method: "POST", json: {} }); setUnread(0); setNotes((n) => n.map((x) => ({ ...x, read: true }))); };

  if (loading || !user) return <div className="flex min-h-screen items-center justify-center"><Spinner className="h-8 w-8" /></div>;

  const sidebar = (
    <nav className="flex h-full flex-col gap-1 p-4" aria-label="Main">
      <Link href="/" className="mb-6 flex items-center gap-3 px-2">
        <div className="relative grid h-10 w-10 place-items-center rounded-xl bg-grad shadow-lg shadow-violet-600/30"><Sparkles className="h-5 w-5 text-slate-900" /></div>
        <div><p className="font-display text-lg font-bold leading-none text-slate-900">SiteForge</p><p className="text-[11px] text-slate-500">AI website factory</p></div>
      </Link>
      {NAV.filter((n) => !n.role || can(n.role)).map((n) => {
        const active = n.href === "/" ? path === "/" || path.startsWith("/sites") : path.startsWith(n.href);
        return (
          <Link key={n.href} href={n.href} className={clsx("relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition", active ? "font-medium text-violet-700" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900")}>
            {active && <motion.span layoutId="nav-active" className="absolute inset-0 rounded-xl border border-violet-200 bg-violet-50" transition={{ type: "spring", stiffness: 400, damping: 32 }} />}
            <n.icon className="relative h-4 w-4" /><span className="relative">{n.label}</span>
          </Link>
        );
      })}
      <div className="mt-auto rounded-xl border border-slate-200 bg-slate-50 p-3">
        <div className="flex items-center gap-2 text-xs text-slate-500"><Cpu className="h-3.5 w-3.5" /> Live updates
          <span className={clsx("ml-auto h-2 w-2 rounded-full", connected ? "bg-emerald-400" : "bg-amber-400 animate-pulse")} /></div>
        <div className="mt-3 flex items-center gap-2">
          <div className="grid h-8 w-8 place-items-center rounded-full bg-gradient-to-br from-violet-500 to-cyan-500 text-xs font-bold">{(user.name || user.email)[0].toUpperCase()}</div>
          <div className="min-w-0 flex-1"><p className="truncate text-xs font-medium text-slate-900">{user.name || user.email}</p><p className="text-[11px] capitalize text-slate-500">{user.role}</p></div>
          <button onClick={logout} aria-label="Sign out" className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-900"><LogOut className="h-4 w-4" /></button>
        </div>
      </div>
    </nav>
  );

  return (
    <EventsCtx.Provider value={subscribe}>
      <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute -left-40 -top-40 h-[520px] w-[520px] animate-aurora rounded-full bg-violet-400/20 blur-[120px]" />
        <div className="absolute -right-40 top-20 h-[460px] w-[460px] animate-aurora rounded-full bg-cyan-300/20 blur-[120px] [animation-delay:-6s]" />
        <div className="absolute bottom-0 left-1/3 h-[420px] w-[420px] animate-aurora rounded-full bg-emerald-300/15 blur-[120px] [animation-delay:-12s]" />
        <div className="grid-bg absolute inset-0" />
      </div>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-slate-200 bg-white/80 backdrop-blur-xl lg:block">{sidebar}</aside>
      <AnimatePresence>
        {open && (
          <motion.div className="fixed inset-0 z-40 bg-slate-900/40 lg:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setOpen(false)}>
            <motion.aside className="h-full w-72 border-r border-slate-200 bg-white" initial={{ x: -300 }} animate={{ x: 0 }} exit={{ x: -300 }} onClick={(e) => e.stopPropagation()}>{sidebar}</motion.aside>
          </motion.div>
        )}
      </AnimatePresence>
      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-slate-200 bg-white/90 px-4 backdrop-blur-xl sm:px-8">
          <button className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu"><Menu className="h-5 w-5" /></button>
          <div className="flex-1" />
          <Link href="/new" className="hidden items-center gap-2 rounded-xl bg-grad px-4 py-2 text-sm font-medium text-white shadow-lg shadow-violet-600/25 sm:flex"><Plus className="h-4 w-4" /> New website</Link>
          <div className="relative">
            <button onClick={() => setBell((b) => !b)} className="relative rounded-xl p-2.5 text-slate-600 hover:bg-slate-100" aria-label={`Notifications (${unread} unread)`}>
              <Bell className="h-5 w-5" />
              <AnimatePresence>{unread > 0 && (
                <motion.span key={unread} initial={{ scale: 0 }} animate={{ scale: 1 }} exit={{ scale: 0 }} className="absolute right-1 top-1 grid h-4 min-w-4 place-items-center rounded-full bg-rose-500 px-1 text-[10px] font-bold text-white">{unread > 99 ? "99+" : unread}</motion.span>
              )}</AnimatePresence>
            </button>
            <AnimatePresence>
              {bell && (
                <motion.div initial={{ opacity: 0, y: -8, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -8, scale: 0.97 }}
                  className="glass-strong absolute right-0 top-12 w-[min(380px,calc(100vw-32px))] overflow-hidden bg-white/90 shadow-2xl shadow-slate-900/10">
                  <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
                    <p className="text-sm font-semibold">Notifications</p>
                    <div className="flex gap-1">
                      <button onClick={markAll} className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 hover:text-slate-900"><CheckCheck className="h-3.5 w-3.5" /> Mark all read</button>
                      <button onClick={() => setBell(false)} className="rounded-lg p-1 text-slate-500 hover:text-slate-900" aria-label="Close"><X className="h-4 w-4" /></button>
                    </div>
                  </div>
                  <div className="max-h-[60vh] overflow-y-auto">
                    {notes.length === 0 && <p className="px-4 py-10 text-center text-sm text-slate-500">You're all caught up.</p>}
                    {notes.map((n) => (
                      <Link key={n.id} href={n.link || "#"} onClick={() => setBell(false)} className={clsx("flex gap-3 border-b border-slate-200 px-4 py-3 hover:bg-slate-50", !n.read && "bg-violet-500/[0.05]")}>
                        <span className={clsx("mt-1.5 h-2 w-2 shrink-0 rounded-full", { info: "bg-indigo-400", success: "bg-emerald-400", warning: "bg-amber-400", error: "bg-rose-500" }[n.level])} />
                        <div className="min-w-0"><p className="text-sm text-slate-900">{n.title}</p><p className="line-clamp-2 text-xs text-slate-500">{n.message}</p><p className="mt-1 text-[11px] text-slate-500">{timeAgo(n.created_at)}</p></div>
                      </Link>
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </header>
        {sandbox && (
          <div role="status" className="border-b border-amber-400/20 bg-amber-500/10 px-4 py-2 text-center text-xs text-amber-700 sm:px-8">
            <strong>Sandbox mode:</strong> Cloudflare and OVH are simulated — domain searches and purchases are fake and nothing is charged.
          </div>
        )}
        <main className="mx-auto max-w-[1400px] px-4 py-8 sm:px-8">{children}</main>
      </div>
    </EventsCtx.Provider>
  );
}
