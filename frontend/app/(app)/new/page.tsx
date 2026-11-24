"use client";

import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, Bot, Check, Eye, Loader2, MessageSquareText, Rocket, Sparkles, Wand2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useToast } from "@/components/toast";
import { Button, ErrorBox, STACK_META } from "@/components/ui";
import { api } from "@/lib/api";
import type { Catalog } from "@/lib/types";

const EXAMPLES = [
  "Create a website about sustainable living. Generate the design, content and images.",
  "An online store selling handmade ceramic coffee mugs",
  "A blog and magazine about indie video game development",
  "A booking portal for a yoga and meditation studio in Lisbon",
  "A landing page for an AI note-taking app for developers",
];

const FLOW = [
  { icon: Sparkles, title: "Build", text: "AI agents design, write and build it" },
  { icon: Eye, title: "Preview", text: "Review it on a private preview link" },
  { icon: MessageSquareText, title: "Request changes", text: "Comment until it's right" },
  { icon: Rocket, title: "Publish", text: "Pick hosting + domain, go live" },
];

export default function NewPage() {
  return <Suspense><NewWebsite /></Suspense>;
}

function NewWebsite() {
  const router = useRouter();
  const toast = useToast();
  const params = useSearchParams();
  const [prompt, setPrompt] = useState(params.get("prompt") ?? "");
  const [cat, setCat] = useState<Catalog | null>(null);
  const [rec, setRec] = useState<any>(null);
  const [thinking, setThinking] = useState(false);
  const [form, setForm] = useState({ name: "", stack: "", reference_url: "", contact_phone: "", contact_email: "" });  // technology is an explicit user choice
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<any>(null);

  useEffect(() => { api<Catalog>("/api/catalog").then(setCat).catch(setError); }, []);
  useEffect(() => {
    if (prompt.trim().length < 8) { setRec(null); return; }
    setThinking(true);
    const t = setTimeout(() => api("/api/stacks/recommend", { method: "POST", json: { prompt } }).then(setRec).catch(() => {}).finally(() => setThinking(false)), 450);
    return () => clearTimeout(t);
  }, [prompt]);

  const missing = [prompt.trim().length < 10 && "an instruction (10+ characters)", !form.stack && "a technology"].filter(Boolean) as string[];

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const r = await api<{ website: { id: string; name: string } }>("/api/websites", { method: "POST", json: { prompt, stack: form.stack, name: form.name || null, reference_url: form.reference_url.trim() || null, contact_phone: form.contact_phone.trim() || null, contact_email: form.contact_email.trim() || null } });
      toast({ title: "Building your preview", message: r.website.name, level: "info" });
      router.push(`/sites/${r.website.id}`);
    } catch (e: any) { setError(e); setBusy(false); }
  };

  return (
    <div className="mx-auto max-w-5xl">
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mb-8 text-center">
        <p className="chip mx-auto mb-4 border-violet-200 bg-violet-50 text-violet-700"><Wand2 className="h-3 w-3" /> New website</p>
        <h1 className="font-display text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl">What should we <span className="text-grad">build</span>?</h1>
        <p className="mt-3 text-slate-500">Describe it and pick the technology. You'll review a live preview before anything is published.</p>
      </motion.div>

      <ol className="mb-8 grid gap-2 sm:grid-cols-4" aria-label="How it works">
        {FLOW.map((s, i) => (
          <motion.li key={s.title} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 * i }}
            className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-violet-50 text-violet-600"><s.icon className="h-4 w-4" /></span>
            <div className="min-w-0"><p className="text-sm font-semibold text-slate-900">{i + 1}. {s.title}</p><p className="truncate text-xs text-slate-500">{s.text}</p></div>
          </motion.li>
        ))}
      </ol>

      <div className="glow-border rounded-3xl bg-white p-2 shadow-sm">
        <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={4} autoFocus aria-label="Website instruction"
          placeholder="Create a website about sustainable living. Generate the design, content and images."
          className="w-full resize-none rounded-2xl bg-transparent px-5 py-4 text-lg text-slate-900 outline-none placeholder:text-slate-400" />
        <div className="flex flex-wrap gap-2 px-4 pb-3">
          {EXAMPLES.map((e) => <button key={e} onClick={() => setPrompt(e)} className="chip transition hover:border-violet-300 hover:text-violet-700">{e.length > 48 ? e.slice(0, 48) + "…" : e}</button>)}
        </div>
      </div>

      <AnimatePresence>
        {(rec || thinking) && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
            <div className="glass mt-4 flex flex-wrap items-center gap-x-6 gap-y-3 p-4">
              <div className="flex items-center gap-2 text-sm font-medium text-violet-700">{thinking ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bot className="h-4 w-4" />} Requirements preview</div>
              {rec && <>
                <Info label="Site name" value={rec.site_name} /><Info label="Topic" value={rec.topic} /><Info label="Theme" value={rec.theme} />
                <Info label="Suggested technology" value={STACK_META[rec.stack]?.label ?? rec.stack} />
                <p className="w-full text-xs text-slate-500">Suggestion only: you choose the technology below. {rec.reason}</p>
              </>}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <section className="mt-10">
        <h2 className="mb-4 flex items-center gap-2 font-display text-lg font-semibold text-slate-900">
          <Sparkles className="h-4 w-4 text-violet-600" />Technology
          {form.stack ? <span className="grid h-5 w-5 place-items-center rounded-full bg-emerald-100 text-emerald-700"><Check className="h-3 w-3" /></span>
            : <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-700">required</span>}
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {cat?.stacks.map((s) => (
            <Choice key={s.key} active={form.stack === s.key} disabled={s.status === "planned"} onClick={() => setForm((f) => ({ ...f, stack: s.key }))} title={s.name}
              badge={s.status === "planned" ? "planned" : rec?.stack === s.key ? "suggested" : s.status !== "available" ? s.status : undefined}
              text={s.status === "planned" ? s.intended_use : `${s.intended_use}: ${s.description}`} grad={STACK_META[s.key]?.color ?? "from-slate-400 to-slate-600"} />
          ))}
        </div>
      </section>

      <section className="mt-10 grid gap-6 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="name">Website name (optional)</label>
          <input id="name" className="input" placeholder={rec?.site_name ?? "AI will name it"} value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
        </div>
        <div>
          <label className="label" htmlFor="reference">Reference website (optional)</label>
          <input id="reference" className="input" placeholder="example.com — we take design & structure ideas" inputMode="url"
            value={form.reference_url} onChange={(e) => setForm((f) => ({ ...f, reference_url: e.target.value }))} />
          <p className="mt-1 text-xs text-slate-500">A public site to draw inspiration from — colours, fonts and layout. Its text is never copied.</p>
        </div>
        <div>
          <label className="label" htmlFor="contact_phone">Contact phone (optional)</label>
          <input id="contact_phone" className="input" placeholder="+33 4 94 00 00 00" inputMode="tel"
            value={form.contact_phone} onChange={(e) => setForm((f) => ({ ...f, contact_phone: e.target.value }))} />
        </div>
        <div>
          <label className="label" htmlFor="contact_email">Contact email (optional)</label>
          <input id="contact_email" className="input" placeholder="contact@yourbusiness.fr" inputMode="email"
            value={form.contact_email} onChange={(e) => setForm((f) => ({ ...f, contact_email: e.target.value }))} />
          <p className="mt-1 text-xs text-slate-500">Shown on the site exactly as entered (contact page), as clickable phone & email links.</p>
        </div>
      </section>

      <div className="sticky bottom-4 z-10 mt-8">
        <div className="glass-strong flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
          <div className="flex-1">
            {error ? <ErrorBox error={error} />
              : missing.length ? <p className="text-sm text-amber-700">Still needed: {missing.join(", ")}.</p>
              : <p className="text-sm text-slate-500">Ready. Nothing is published and no domain is bought until you click Publish.</p>}
          </div>
          <Button size="lg" onClick={submit} loading={busy} disabled={missing.length > 0}>Build preview <ArrowRight className="h-4 w-4" /></Button>
        </div>
      </div>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return <div><p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p><motion.p key={value} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="text-sm font-medium capitalize text-slate-900">{value}</motion.p></div>;
}

function Choice({ active, disabled, onClick, title, text, badge, grad }: { active: boolean; disabled?: boolean; onClick: () => void; title: string; text: string; badge?: string; grad: string }) {
  return (
    <motion.button whileHover={disabled ? {} : { y: -2 }} whileTap={disabled ? {} : { scale: 0.98 }} onClick={onClick} disabled={disabled} aria-pressed={active}
      className={clsx("relative overflow-hidden rounded-2xl border bg-white p-4 text-left shadow-sm transition disabled:cursor-not-allowed disabled:opacity-40",
        active ? "border-violet-500 ring-4 ring-violet-500/10" : "border-slate-200 hover:border-slate-300 hover:shadow-md")}>
      <div className="flex items-center gap-3">
        <span className={clsx("h-8 w-8 shrink-0 rounded-lg bg-gradient-to-br", grad)} />
        <div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold text-slate-900">{title}</p></div>
        {badge && <span className={clsx("rounded-full px-2 py-0.5 text-[10px] font-medium capitalize", badge === "suggested" ? "bg-violet-100 text-violet-700" : "bg-slate-100 text-slate-600")}>{badge}</span>}
        <AnimatePresence>{active && <motion.span initial={{ scale: 0 }} animate={{ scale: 1 }} exit={{ scale: 0 }} className="grid h-5 w-5 place-items-center rounded-full bg-violet-600 text-white"><Check className="h-3 w-3" /></motion.span>}</AnimatePresence>
      </div>
      <p className="mt-2 line-clamp-2 text-xs text-slate-500">{text}</p>
    </motion.button>
  );
}
