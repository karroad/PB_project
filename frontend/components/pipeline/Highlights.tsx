"use client";

import { motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, ExternalLink, XCircle } from "lucide-react";
import { absoluteUrl } from "@/lib/api";
import type { Highlight } from "@/lib/types";

const stagger = { hidden: {}, show: { transition: { staggerChildren: 0.06 } } };
const pop = { hidden: { opacity: 0, y: 8, scale: 0.9 }, show: { opacity: 1, y: 0, scale: 1, transition: { type: "spring" as const, stiffness: 420, damping: 24 } } };

export function Highlights({ items }: { items: Highlight[] }) {
  return (
    <div className="mt-3 space-y-3">
      {items.map((h, i) => <One key={i} h={h} />)}
    </div>
  );
}

function One({ h }: { h: Highlight }) {
  switch (h.type) {
    case "kv":
      return (
        <motion.dl variants={stagger} initial="hidden" animate="show" className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {h.items?.map((it: any) => (
            <motion.div variants={pop} key={it.label} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <dt className="text-[10px] uppercase tracking-wider text-slate-500">{it.label}</dt>
              <dd className="mt-0.5 break-words text-xs text-slate-700">{String(it.value)}</dd>
            </motion.div>
          ))}
        </motion.dl>
      );
    case "chips":
      return (
        <div>
          {h.label && <p className="mb-1.5 text-[10px] uppercase tracking-wider text-slate-500">{h.label}</p>}
          <motion.div variants={stagger} initial="hidden" animate="show" className="flex flex-wrap gap-1.5">
            {h.items?.map((c: string, i: number) => <motion.span variants={pop} key={`${i}-${c}`} className="chip">{c}</motion.span>)}
          </motion.div>
        </div>
      );
    case "palette":
      return (
        <motion.div variants={stagger} initial="hidden" animate="show" className="flex flex-wrap gap-2">
          {h.items?.map((c: any) => (
            <motion.div variants={pop} key={c.name} className="flex flex-col items-center gap-1">
              <div className="h-11 w-11 rounded-xl border border-slate-300 shadow-lg" style={{ background: c.hex, boxShadow: `0 8px 24px -8px ${c.hex}` }} />
              <span className="text-[10px] text-slate-500">{c.name}</span>
              <span className="font-mono text-[10px] text-slate-500">{c.hex}</span>
            </motion.div>
          ))}
        </motion.div>
      );
    case "fonts":
      return (
        <div className="flex flex-wrap gap-2">
          {h.items?.map((f: string, i: number) => (
            <div key={f} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <p className="text-[10px] uppercase tracking-wider text-slate-500">{i === 0 ? "Headings" : "Body"}</p>
              <p className="text-sm text-slate-900">{f}</p>
            </div>
          ))}
        </div>
      );
    case "images":
      return (
        <motion.div variants={stagger} initial="hidden" animate="show" className="grid grid-cols-3 gap-2 sm:grid-cols-4">
          {h.items?.map((im: any) => (
            <motion.figure variants={pop} key={im.url} className="group relative aspect-video overflow-hidden rounded-lg border border-slate-200 bg-slate-100">
              <img src={absoluteUrl(im.url)} alt={im.label} className="h-full w-full object-cover transition duration-500 group-hover:scale-110" loading="lazy" />
              <figcaption className="absolute inset-x-0 bottom-0 truncate bg-gradient-to-t from-black/80 to-transparent px-1.5 pb-1 pt-3 text-[9px] text-slate-200">{im.label}</figcaption>
            </motion.figure>
          ))}
        </motion.div>
      );
    case "checks":
      return (
        <motion.ul variants={stagger} initial="hidden" animate="show" className="grid gap-1">
          {h.items?.map((c: any) => (
            <motion.li variants={pop} key={c.name} className="flex min-w-0 items-start gap-2 rounded-lg bg-slate-50 px-2.5 py-1.5 text-xs">
              {c.status === "pass" ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" aria-label="pass" />
                : c.status === "warn" ? <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" aria-label="warning" />
                : <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-rose-600" aria-label="fail" />}
              <span className="shrink-0 font-medium text-slate-700">{c.name}</span>
              <span className="min-w-0 flex-1 truncate pl-2 text-right text-slate-500" title={c.detail}>{c.detail}</span>
            </motion.li>
          ))}
        </motion.ul>
      );
    case "link":
      return (
        <a href={h.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-xl bg-emerald-500/15 px-3 py-2 text-sm font-medium text-emerald-700 ring-1 ring-emerald-500/30 hover:bg-emerald-500/25">
          {h.label} <ExternalLink className="h-3.5 w-3.5" />
        </a>
      );
    default:
      return null;
  }
}
