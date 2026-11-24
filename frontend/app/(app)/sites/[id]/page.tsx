"use client";

import clsx from "clsx";
import { motion } from "framer-motion";
import {
  Archive, ArrowLeft, Code2, ExternalLink, Eye, FileText, Gauge, History, Inbox, LayoutTemplate, MessageSquareText, Monitor, Palette, Power, RefreshCw, Rocket, RotateCcw, Search, Send, Settings, Smartphone, Tablet, Trash2, Workflow,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Highlights } from "@/components/pipeline/Highlights";
import { PipelineView } from "@/components/pipeline/PipelineView";
import { PublishPanel } from "@/components/PublishPanel";
import { usePlatformEvents } from "@/components/Shell";
import { useToast } from "@/components/toast";
import { Button, Card, Empty, ErrorBox, HealthDot, Modal, Spinner, StackBadge, StatusBadge } from "@/components/ui";
import { api, timeAgo } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Deployment, Job, Website } from "@/lib/types";

const TABS = [
  { key: "pipeline", label: "Pipeline", icon: Workflow }, { key: "preview", label: "Preview", icon: Eye },
  { key: "changes", label: "Changes", icon: MessageSquareText },
  { key: "brand", label: "Brand & plan", icon: Palette }, { key: "content", label: "Content", icon: FileText },
  { key: "seo", label: "SEO", icon: Search },
  { key: "quality", label: "Quality", icon: Gauge }, { key: "deployments", label: "Deployments", icon: History },
  { key: "code", label: "Code", icon: Code2 }, { key: "monitoring", label: "Health", icon: Power },
  { key: "submissions", label: "Leads", icon: Inbox }, { key: "settings", label: "Settings", icon: Settings },
];

export default function SitePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const { can } = useAuth();
  const [site, setSite] = useState<Website | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [tab, setTab] = useState("pipeline");
  const [busy, setBusy] = useState("");
  const [del, setDel] = useState(false);
  const [pub, setPub] = useState(false);
  const [error, setError] = useState<any>(null);

  const load = useCallback(async () => {
    try {
      const r = await api<{ website: Website; latest_job: Job | null }>(`/api/websites/${id}`);
      setSite(r.website);
      setJob(r.latest_job);  // PipelineView is keyed by job id, so a status refresh doesn't remount it
    } catch (e) { setError(e); }
  }, [id]);
  useEffect(() => { load(); }, [load]);
  usePlatformEvents((ev) => { if (ev.website_id === id && ["job_completed", "job_failed", "health", "approval_required"].includes(ev.type)) load(); });

  const startJob = (j: Job, msg: string) => { toast({ title: msg, level: "success" }); setJob(j); setTab("pipeline"); load(); };
  const action = async (name: string, fn: () => Promise<any>, msg: string) => {
    setBusy(name);
    try {
      const r = await fn();
      if (r?.steps) startJob(r, msg); else { toast({ title: msg, level: "success" }); await load(); }
    } catch (e: any) { toast({ title: `${name} failed`, message: e.message, level: "error" }); }
    finally { setBusy(""); }
  };

  if (error) return <ErrorBox error={error} />;
  if (!site) return <div className="flex justify-center py-24"><Spinner className="h-8 w-8" /></div>;
  const p = site.palette;
  const running = !!job && ["queued", "running", "awaiting_approval"].includes(job.status);
  const preview = site.config?.preview as { url: string; published?: boolean; built_at?: string; revision?: number } | undefined;
  const unpublished = !!preview && !preview.published;
  const blocked = running || site.status === "archived";

  return (
    <div>
      <Link href="/" className="mb-5 inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-900"><ArrowLeft className="h-4 w-4" /> All websites</Link>
      <div className="relative mb-6 overflow-hidden rounded-3xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="absolute inset-x-0 top-0 h-1.5" style={{ background: p ? `linear-gradient(90deg, ${p.primary}, ${p.secondary} 55%, ${p.accent})` : "linear-gradient(90deg,#8b5cf6,#22d3ee)" }} />
        <div className="absolute -right-24 -top-24 h-64 w-64 rounded-full opacity-[0.12] blur-3xl" style={{ background: p?.primary ?? "#8b5cf6" }} />
        <div className="relative flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2"><StatusBadge status={site.status} /><StackBadge stack={site.stack} ai={site.stack_selected_by === "ai"} />{site.status === "live" && <HealthDot health={site.health_status} />}</div>
            <h1 className="mt-3 font-display text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">{site.name}</h1>
            <p className="mt-1 max-w-2xl text-sm text-slate-600">{site.tagline || site.prompt}</p>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
              {site.live_url && <a href={site.live_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 font-medium text-emerald-700 hover:underline">Live: {site.live_url} <ExternalLink className="h-3.5 w-3.5" /></a>}
              {preview && <a href={preview.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 font-medium text-violet-700 hover:underline">Preview <ExternalLink className="h-3.5 w-3.5" /></a>}
            </div>
            {unpublished && site.status === "live" && <p className="mt-2 inline-flex rounded-lg bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-800 ring-1 ring-amber-200">The preview has changes that aren't live yet</p>}
          </div>
          {can("operator") && (
            <div className="flex flex-wrap gap-2">
              {preview && (unpublished || site.status !== "live") && site.status !== "archived" && (
                <Button disabled={blocked} onClick={() => setPub(true)}><Rocket className="h-4 w-4" /> {site.status === "live" ? "Publish changes" : "Publish"}</Button>
              )}
              {preview && <Button variant="ghost" disabled={blocked} onClick={() => setTab("changes")}><MessageSquareText className="h-4 w-4" /> Request changes</Button>}
              {site.status === "live" && <Button variant="ghost" disabled={blocked} loading={busy === "Redeploy"} onClick={() => action("Redeploy", () => api(`/api/websites/${id}/redeploy`, { method: "POST" }), "Redeploy started")}><RefreshCw className="h-4 w-4" /> Redeploy</Button>}
              <Button variant="ghost" disabled={blocked} loading={busy === "Regenerate"} onClick={() => action("Regenerate", () => api(`/api/websites/${id}/regenerate?scope=content`, { method: "POST" }), "Rewriting content for the preview")}><LayoutTemplate className="h-4 w-4" /> New content</Button>
              {site.status === "archived"
                ? <Button variant="ghost" loading={busy === "Restore"} onClick={() => action("Restore", () => api(`/api/websites/${id}/restore`, { method: "POST" }), "Restored")}><RotateCcw className="h-4 w-4" /> Restore</Button>
                : <Button variant="ghost" disabled={running} loading={busy === "Archive"} onClick={() => action("Archive", () => api(`/api/websites/${id}/archive`, { method: "POST" }), "Archived")}><Archive className="h-4 w-4" /> Archive</Button>}
              {can("admin") && <Button variant="danger" onClick={() => setDel(true)} aria-label="Delete website"><Trash2 className="h-4 w-4" /></Button>}
            </div>
          )}
        </div>
      </div>

      <div className="mb-6 flex gap-1 overflow-x-auto rounded-xl border border-slate-200 bg-white p-1 shadow-sm" role="tablist">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)} className={clsx("relative flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition", tab === t.key ? "text-violet-700" : "text-slate-500 hover:text-slate-900")}>
            {tab === t.key && <motion.span layoutId="site-tab" className="absolute inset-0 rounded-lg bg-violet-50" />}<t.icon className="relative h-3.5 w-3.5" /><span className="relative">{t.label}</span>
          </button>
        ))}
      </div>

      <motion.div key={tab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
        {tab === "pipeline" && (job ? <PipelineView key={job.id} jobId={job.id} liveUrl={site.live_url} previewUrl={preview?.url} onFinished={() => load()}
          onPublish={can("operator") ? () => setPub(true) : undefined} onRequestChanges={can("operator") ? () => setTab("changes") : undefined} /> : <Empty icon={Workflow} title="No jobs yet" />)}
        {tab === "preview" && <Preview site={site} />}
        {tab === "changes" && <Changes site={site} disabled={blocked} onStarted={(j) => startJob(j, "Applying your changes to the preview")} />}
        {tab === "brand" && <Brand site={site} disabled={blocked} onStarted={(j) => startJob(j, "Applying your changes to the preview")} />}
        {tab === "content" && <Content site={site} disabled={blocked} onStarted={(j) => startJob(j, "Applying your changes to the preview")} />}
        {tab === "seo" && <SeoEditor site={site} disabled={blocked} onStarted={(j) => startJob(j, "Applying your changes to the preview")} />}
        {tab === "quality" && <Quality site={site} />}
        {tab === "deployments" && <Deployments site={site} onChange={load} />}
        {tab === "code" && <CodeView site={site} />}
        {tab === "monitoring" && <HealthTab site={site} />}
        {tab === "submissions" && <Submissions site={site} />}
        {tab === "settings" && <SiteSettings site={site} onSaved={load} />}
      </motion.div>

      <Modal open={pub} onClose={() => setPub(false)} title={site.status === "live" ? "Publish changes" : "Publish website"} wide>
        <PublishPanel site={site} onCancel={() => setPub(false)} onPublished={(j) => { setPub(false); startJob(j, "Publishing started"); }} />
      </Modal>
      <DeleteModal open={del} onClose={() => setDel(false)} site={site} onDeleted={() => router.push("/")} />
    </div>
  );
}

// Direct editors reuse the revision pipeline: they build a plain-language instruction and
// POST it to /changes (same endpoint as "Request changes"), which re-renders the preview.
async function applyEdit(siteId: string, instruction: string) {
  return api<Job>(`/api/websites/${siteId}/changes`, { method: "POST", json: { instruction } });
}
const quo = (s: string) => `"${s.replace(/["“”]/g, "'").replace(/\s+/g, " ").trim()}"`;
function normHex(h?: string) {
  const v = (h ?? "").trim().replace(/^#/, "");
  if (/^[0-9a-fA-F]{6}$/.test(v)) return "#" + v;
  if (/^[0-9a-fA-F]{3}$/.test(v)) return "#" + v.split("").map((x) => x + x).join("");
  return "#888888";
}

function Changes({ site, disabled, onStarted }: { site: Website; disabled: boolean; onStarted: (j: Job) => void }) {
  const [text, setText] = useState("");
  const [data, setData] = useState<{ ai: boolean; examples: string[]; revisions: any[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  useEffect(() => { api(`/api/websites/${site.id}/revisions`).then(setData).catch(() => {}); }, [site.id, site.updated_at]);
  const send = async () => {
    setBusy(true); setErr(null);
    try { const j = await api<Job>(`/api/websites/${site.id}/changes`, { method: "POST", json: { instruction: text } }); setText(""); onStarted(j); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  };
  if (!site.config?.preview) return <Empty icon={MessageSquareText} title="Wait for the preview" text="You can request changes once the first preview is ready." />;
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
      <Card className="h-fit">
        <h3 className="font-display text-lg font-semibold text-slate-900">Request changes</h3>
        <p className="mt-1 text-sm text-slate-500">Describe what to change. It's applied to the <strong>preview</strong>; the live site only changes when you publish.</p>
        <div className="glow-border mt-4 rounded-2xl bg-white">
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={6} aria-label="Change request"
            placeholder={'e.g. Change the headline to "Live lighter, waste less" and use a dark green primary colour'}
            className="w-full resize-none rounded-2xl bg-transparent px-4 py-3 text-sm text-slate-900 outline-none placeholder:text-slate-500" />
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {(data?.examples ?? []).slice(0, 6).map((e) => <button key={e} onClick={() => setText((t) => (t ? t + "\n" : "") + e)} className="chip hover:border-violet-300 hover:text-violet-700">{e.length > 46 ? e.slice(0, 46) + "…" : e}</button>)}
        </div>
        {data && !data.ai && <p className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500 ring-1 ring-slate-200">Offline mode understands common edits (colours, theme, fonts, headline, tagline, FAQs, articles, menu). Add an Anthropic key for any free-form request.</p>}
        <div className="mt-3"><ErrorBox error={err} /></div>
        <div className="mt-4 flex justify-end"><Button onClick={send} loading={busy} disabled={disabled || text.trim().length < 3}><Send className="h-4 w-4" /> Apply to preview</Button></div>
      </Card>
      <div>
        <h3 className="mb-3 font-display text-lg font-semibold text-slate-900">History</h3>
        {!data ? <Spinner /> : !data.revisions.length ? <p className="text-sm text-slate-500">No change requests yet.</p> : (
          <ol className="space-y-3">
            {data.revisions.map((r) => (
              <li key={r.n} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="flex items-center gap-2 text-xs text-slate-500"><span className="rounded-md bg-violet-50 px-1.5 py-0.5 font-semibold text-violet-700">#{r.n}</span>{timeAgo(r.at)}</div>
                <p className="mt-2 whitespace-pre-line text-sm text-slate-800">“{r.instruction}”</p>
                <ul className="mt-2 space-y-0.5">{r.summary.map((s: string) => <li key={s} className="text-xs text-emerald-700">✓ {s}</li>)}</ul>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}

function Preview({ site }: { site: Website }) {
  const preview = site.config?.preview as { url: string } | undefined;
  const [which, setWhich] = useState<"preview" | "live">(preview ? "preview" : "live");
  const [w, setW] = useState("100%");
  const [k, setK] = useState(0);
  const url = which === "preview" ? preview?.url : site.live_url;
  if (!preview && !site.live_url) return <Empty icon={Monitor} title="No preview yet" text="The preview appears as soon as the build passes its quality checks." />;
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex rounded-xl border border-slate-200 bg-white p-1 shadow-sm">
          {(["preview", "live"] as const).map((v) => (
            <button key={v} disabled={v === "preview" ? !preview : !site.live_url} onClick={() => setWhich(v)}
              className={clsx("rounded-lg px-3 py-1.5 text-xs font-medium capitalize transition disabled:opacity-40", which === v ? "bg-violet-50 text-violet-700" : "text-slate-500 hover:text-slate-900")}>{v === "live" ? "Live site" : "Preview"}</button>
          ))}
        </div>
        {[["100%", Monitor], ["820px", Tablet], ["390px", Smartphone]].map(([v, I]: any) => (
          <button key={v} onClick={() => setW(v)} aria-label={`Preview width ${v}`} className={clsx("rounded-lg p-2", w === v ? "bg-violet-50 text-violet-700" : "text-slate-500 hover:text-slate-900")}><I className="h-4 w-4" /></button>
        ))}
        <button onClick={() => setK((x) => x + 1)} className="rounded-lg p-2 text-slate-500 hover:text-slate-900" aria-label="Reload preview"><RefreshCw className="h-4 w-4" /></button>
        <a href={url ?? "#"} target="_blank" rel="noreferrer" className="ml-auto truncate font-mono text-xs text-slate-500 hover:text-violet-700">{url}</a>
      </div>
      <div className="flex justify-center rounded-2xl border border-slate-200 bg-slate-100 p-3">
        {url && <motion.iframe key={`${which}-${k}`} layout src={url} title={which === "preview" ? "Website preview" : "Live website"} style={{ width: w }} className="h-[75vh] max-w-full rounded-xl bg-white shadow-sm" />}
      </div>
    </div>
  );
}

function Brand({ site, disabled, onStarted }: { site: Website; disabled: boolean; onStarted: (j: Job) => void }) {
  const c = site.config ?? {};
  if (!c.brand) return <Empty icon={Palette} title="Brand not generated yet" />;
  const SLOTS = ["primary", "secondary", "accent", "background", "surface", "text"];
  const base = c.brand.palette as Record<string, string>;
  const [pal, setPal] = useState<Record<string, string>>(() => ({ ...base }));
  const [fh, setFh] = useState<string>(c.brand.fonts?.heading ?? "");
  const [fb, setFb] = useState<string>(c.brand.fonts?.body ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  const canPreview = !!site.config?.preview;
  const eq = (a?: string, b?: string) => (a ?? "").toLowerCase() === (b ?? "").toLowerCase();
  const dirty = SLOTS.some((s) => !eq(pal[s], base[s])) || fh !== (c.brand.fonts?.heading ?? "") || fb !== (c.brand.fonts?.body ?? "");
  const apply = async () => {
    const lines: string[] = [];
    SLOTS.forEach((s) => { if (!eq(pal[s], base[s]) && pal[s]) lines.push(`Change ${s} colour to ${normHex(pal[s])}`); });
    if (fh && fh !== (c.brand.fonts?.heading ?? "")) lines.push(`Use ${fh} for headings`);
    if (fb && fb !== (c.brand.fonts?.body ?? "")) lines.push(`Use ${fb} for body`);
    if (!lines.length) return;
    setBusy(true); setErr(null);
    try { const j = await applyEdit(site.id, lines.join("\n")); onStarted(j); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
      <Card className="lg:col-span-2">
        <h3 className="mb-1 font-display font-semibold">Edit colours &amp; fonts</h3>
        <p className="mb-4 text-sm text-slate-500">Change colours and fonts after generation. Applied to the <strong>preview</strong>; the live site only changes when you publish.</p>
        {!canPreview ? <p className="text-sm text-slate-500">Available once the first preview is ready.</p> : (<>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {SLOTS.map((s) => (
              <div key={s}>
                <label className="label capitalize">{s}</label>
                <div className="flex items-center gap-2">
                  <input type="color" aria-label={s} value={normHex(pal[s])} onChange={(e) => setPal((p) => ({ ...p, [s]: e.target.value }))} className="h-9 w-9 shrink-0 cursor-pointer rounded border border-slate-200 bg-white p-0.5" />
                  <input className="input font-mono text-xs" value={pal[s] ?? ""} onChange={(e) => setPal((p) => ({ ...p, [s]: e.target.value }))} />
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div><label className="label">Heading font</label><input className="input" value={fh} onChange={(e) => setFh(e.target.value)} placeholder="e.g. Manrope" /></div>
            <div><label className="label">Body font</label><input className="input" value={fb} onChange={(e) => setFb(e.target.value)} placeholder="e.g. Source Sans 3" /></div>
          </div>
          <div className="mt-3"><ErrorBox error={err} /></div>
          <div className="mt-4 flex justify-end"><Button onClick={apply} loading={busy} disabled={disabled || !dirty}><Palette className="h-4 w-4" /> Apply to preview</Button></div>
        </>)}
      </Card>
      <Card><h3 className="mb-3 font-display font-semibold">Identity</h3>
        <p className="text-2xl font-bold" style={{ color: c.brand.palette.secondary }}>{c.brand.name}</p><p className="text-sm text-slate-500">{c.brand.tagline}</p>
        <Highlights items={[{ type: "palette", items: Object.entries(c.brand.palette).map(([name, hex]) => ({ name, hex })) }, { type: "fonts", items: [c.brand.fonts.heading, c.brand.fonts.body] },
          { type: "kv", items: [{ label: "Style", value: c.brand.style }, { label: "Voice", value: c.brand.voice }] }]} /></Card>
      <Card><h3 className="mb-3 font-display font-semibold">Requirements</h3>
        <Highlights items={[{ type: "kv", items: [{ label: "Topic", value: c.requirements?.topic_title }, { label: "Audience", value: c.requirements?.audience }, { label: "Purpose", value: c.requirements?.purpose }, { label: "Tone", value: c.requirements?.tone }] },
          { type: "chips", label: "Features", items: c.requirements?.features ?? [] }]} /></Card>
      <Card className="lg:col-span-2"><h3 className="mb-3 font-display font-semibold">Plan</h3>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {c.plan?.sitemap?.map((pg: any) => (
            <div key={pg.slug} className="rounded-xl border border-slate-200 bg-slate-50 p-3"><p className="font-medium text-slate-900">{pg.title} <span className="font-mono text-xs text-slate-500">/{pg.slug}</span></p><p className="mt-1 text-xs text-slate-500">{pg.purpose}</p>
              <div className="mt-2 flex flex-wrap gap-1">{pg.sections?.map((s: string) => <span key={s} className="chip">{s}</span>)}</div></div>
          ))}
        </div>
        <p className="mt-4 text-sm text-slate-500">{c.plan?.design_direction}</p>
      </Card>
    </div>
  );
}

function Content({ site, disabled, onStarted }: { site: Website; disabled: boolean; onStarted: (j: Job) => void }) {
  const c = site.config?.content;
  if (!c) return <Empty icon={FileText} title="No content yet" />;
  const review = site.config?.content_review;
  const tag0 = site.config?.brand?.tagline ?? "";
  const cta0 = c.home.cta_primary ?? "";
  const [hero, setHero] = useState<string>(c.home.hero_title ?? "");
  const [sub, setSub] = useState<string>(c.home.hero_subtitle ?? "");
  const [tag, setTag] = useState<string>(tag0);
  const [cta, setCta] = useState<string>(cta0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  const canPreview = !!site.config?.preview;
  const dirty = hero !== (c.home.hero_title ?? "") || sub !== (c.home.hero_subtitle ?? "") || tag !== tag0 || cta !== cta0;
  const run = async (instruction: string) => {
    setBusy(true); setErr(null);
    try { const j = await applyEdit(site.id, instruction); onStarted(j); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const saveText = () => {
    const lines: string[] = [];
    if (hero !== (c.home.hero_title ?? "")) lines.push(`Change the headline to ${quo(hero)}`);
    if (sub !== (c.home.hero_subtitle ?? "")) lines.push(`Change the subtitle to ${quo(sub)}`);
    if (tag !== tag0) lines.push(`Change the tagline to ${quo(tag)}`);
    if (cta !== cta0) lines.push(`Change the main button to ${quo(cta)}`);
    if (lines.length) run(lines.join("\n"));
  };
  return (
    <div className="space-y-5">
      {review?.flags?.length > 0 && <div className="rounded-xl border border-amber-400/30 bg-amber-500/10 p-4 text-sm text-amber-700"><p className="font-medium">Flagged for human review</p><ul className="mt-1 list-disc pl-5 text-xs">{review.flags.map((f: string) => <li key={f}>{f}</li>)}</ul></div>}
      <Card>
        <div className="mb-3 flex items-center justify-between gap-3">
          <h3 className="font-display font-semibold">Edit text</h3>
          {canPreview && <span className="text-xs text-slate-500">Edit directly, or let Claude rewrite it. Applied to the preview.</span>}
        </div>
        {!canPreview ? <p className="text-sm text-slate-500">Available once the first preview is ready.</p> : (<>
          <div className="space-y-3">
            {[["Headline", hero, setHero, "Rewrite the headline to be fresh, specific and compelling"],
              ["Subtitle", sub, setSub, "Rewrite the hero subtitle to be clearer and more engaging"],
              ["Tagline", tag, setTag, "Rewrite the tagline to be short and memorable"],
              ["Main button", cta, setCta, "Rewrite the main call-to-action button label"]].map(([label, val, setter, rw]: any) => (
              <div key={label}>
                <label className="label">{label}</label>
                <div className="flex items-start gap-2">
                  <textarea rows={label === "Headline" || label === "Subtitle" ? 2 : 1} className="input flex-1" value={val} onChange={(e) => setter(e.target.value)} />
                  <button type="button" disabled={disabled || busy} onClick={() => run(rw)} title="Rewrite with Claude"
                    className="shrink-0 rounded-lg border border-violet-200 bg-violet-50 px-2.5 py-2 text-xs font-medium text-violet-700 hover:bg-violet-100 disabled:opacity-40">✨ Rewrite</button>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3"><ErrorBox error={err} /></div>
          <div className="mt-4 flex justify-end"><Button onClick={saveText} loading={busy} disabled={disabled || !dirty}><Send className="h-4 w-4" /> Save text to preview</Button></div>
        </>)}
        <p className="mt-4 text-xs text-slate-500">Originality across portfolio: {Math.round((site.config?.originality?.score ?? 1) * 100)}%</p>
      </Card>
      <div className="grid gap-4 md:grid-cols-2">
        {c.articles.map((a: any) => (
          <Card key={a.slug}><span className="chip">{a.category}</span><h3 className="mt-2 font-display font-semibold">{a.title}</h3><p className="mt-1 line-clamp-4 text-sm text-slate-500">{a.body.join(" ")}</p></Card>
        ))}
      </div>
      <Card><h3 className="mb-3 font-display font-semibold">FAQ</h3>{c.faq.map((f: any) => <details key={f.q} className="border-b border-slate-200 py-2"><summary className="cursor-pointer text-sm text-slate-900">{f.q}</summary><p className="mt-1 text-sm text-slate-500">{f.a}</p></details>)}</Card>
    </div>
  );
}

function SeoEditor({ site, disabled, onStarted }: { site: Website; disabled: boolean; onStarted: (j: Job) => void }) {
  const c = site.config ?? {};
  const seoPages: Record<string, { title?: string; description?: string; keywords?: string[] }> = c.seo?.pages ?? {};
  const canPreview = !!site.config?.preview;
  if (!c.seo) return <Empty icon={Search} title="SEO not generated yet" />;

  const pageList: { key: string; label: string }[] = [
    ...(c.plan?.sitemap ?? []).map((p: any) => ({ key: p.slug ?? "", label: p.slug ? p.title : "Home" })),
    ...(c.content?.articles ?? []).map((a: any) => ({ key: `blog/${a.slug}`, label: `Blog: ${a.title}` })),
  ];
  const base = (key: string) => ({ title: seoPages[key]?.title ?? "", description: seoPages[key]?.description ?? "", keywords: (seoPages[key]?.keywords ?? []).join(", ") });
  const [vals, setVals] = useState<Record<string, { title: string; description: string; keywords: string }>>(
    () => Object.fromEntries(pageList.map((p) => [p.key, base(p.key)])));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  const set = (key: string, field: "title" | "description" | "keywords", v: string) => setVals((x) => ({ ...x, [key]: { ...x[key], [field]: v } }));
  const dirty = pageList.some((p) => JSON.stringify(vals[p.key]) !== JSON.stringify(base(p.key)));

  const run = async (instruction: string) => {
    setBusy(true); setErr(null);
    try { const j = await applyEdit(site.id, instruction); onStarted(j); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  };

  // The backend parses one structured edit per line — a literal newline in a textarea value (e.g. the
  // description) would otherwise truncate it, so any line breaks are collapsed to a single space first.
  const oneLine = (s: string) => s.replace(/\s*\n+\s*/g, " ").trim();
  const saveAll = () => {
    const lines: string[] = [];
    pageList.forEach((p) => {
      const b = base(p.key), v = vals[p.key];
      // One structured line per field — parsed deterministically on the backend (no AI call, no
      // ambiguity with other edit types), matching exactly what the Revision agent expects.
      if (v.title !== b.title) lines.push(`SEO title for page "${p.key}": ${oneLine(v.title)}`);
      if (v.description !== b.description) lines.push(`SEO description for page "${p.key}": ${oneLine(v.description)}`);
      if (v.keywords !== b.keywords) lines.push(`SEO keywords for page "${p.key}": ${oneLine(v.keywords)}`);
    });
    if (lines.length) run(lines.join("\n"));
  };
  const optimizeAll = () => run(
    "Rewrite the SEO title, description and keywords for every page in seo.pages to optimise for search engines: titles under 60 " +
    "characters, descriptions under 155 characters, accurate, specific and compelling, each with relevant keywords. Keep every other field identical.");
  const optimizeOne = (key: string, label: string) => run(
    `Rewrite the SEO title, description and keywords for the page "${label}" (seo.pages["${key}"]) to optimise it for search engines: ` +
    "title under 60 characters, description under 155 characters, accurate and compelling, relevant keywords. Keep every other field identical.");

  return (
    <div className="space-y-5">
      <Card>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="font-display font-semibold">Search engine optimisation</h3>
            <p className="mt-1 text-sm text-slate-500">Edit each page's meta title, description and keywords directly, or let Claude optimise them for you.</p>
          </div>
          {canPreview && <Button variant="ghost" onClick={optimizeAll} loading={busy} disabled={disabled}>✨ Optimise all with Claude</Button>}
        </div>
        {!canPreview ? <p className="text-sm text-slate-500">Available once the first preview is ready.</p> : (
          <div className="space-y-4">
            {pageList.map((p) => (
              <div key={p.key} className="rounded-xl border border-slate-200 p-4">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="font-medium text-slate-900">{p.label}</p>
                  <button type="button" disabled={disabled || busy} onClick={() => optimizeOne(p.key, p.label)}
                    className="shrink-0 rounded-lg border border-violet-200 bg-violet-50 px-2.5 py-1.5 text-xs font-medium text-violet-700 hover:bg-violet-100 disabled:opacity-40">✨ Optimise</button>
                </div>
                <div className="grid gap-3">
                  <div><label className="label">Meta title <span className="text-slate-400">({(vals[p.key]?.title ?? "").length}/60)</span></label>
                    <input className="input" value={vals[p.key]?.title ?? ""} onChange={(e) => set(p.key, "title", e.target.value)} /></div>
                  <div><label className="label">Meta description <span className="text-slate-400">({(vals[p.key]?.description ?? "").length}/155)</span></label>
                    <textarea rows={2} className="input" value={vals[p.key]?.description ?? ""} onChange={(e) => set(p.key, "description", e.target.value)} /></div>
                  <div><label className="label">Keywords (comma-separated)</label>
                    <input className="input" value={vals[p.key]?.keywords ?? ""} onChange={(e) => set(p.key, "keywords", e.target.value)} /></div>
                </div>
              </div>
            ))}
            <div className="mt-2"><ErrorBox error={err} /></div>
            <div className="flex justify-end"><Button onClick={saveAll} loading={busy} disabled={disabled || !dirty}><Send className="h-4 w-4" /> Save SEO to preview</Button></div>
          </div>
        )}
      </Card>
    </div>
  );
}

function Quality({ site }: { site: Website }) {
  const q = site.config?.quality;
  if (!q) return <Empty icon={Gauge} title="Not tested yet" />;
  const color = q.score >= 85 ? "#34d399" : q.score >= 65 ? "#fbbf24" : "#f43f5e";
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
      <Card className="flex flex-col items-center justify-center text-center">
        <div className="relative h-40 w-40">
          <svg viewBox="0 0 120 120" className="-rotate-90"><circle cx="60" cy="60" r="52" fill="none" stroke="rgba(255,255,255,.07)" strokeWidth="10" />
            <motion.circle cx="60" cy="60" r="52" fill="none" stroke={color} strokeWidth="10" strokeLinecap="round" strokeDasharray={327} initial={{ strokeDashoffset: 327 }} animate={{ strokeDashoffset: 327 * (1 - q.score / 100) }} transition={{ duration: 1.2 }} /></svg>
          <div className="absolute inset-0 grid place-items-center"><div><p className="font-display text-4xl font-bold">{q.score}</p><p className="text-xs text-slate-500">/ 100</p></div></div>
        </div>
        <p className="mt-3 text-sm text-slate-600">{q.passed} passed · {q.warnings} warnings · {q.failed} failed</p>
        <p className="text-xs text-slate-500">{q.pages} pages crawled</p>
      </Card>
      <Card><h3 className="mb-3 font-display font-semibold">Checks</h3><Highlights items={[{ type: "checks", items: q.checks }]} /></Card>
    </div>
  );
}

function Deployments({ site, onChange }: { site: Website; onChange: () => void }) {
  const toast = useToast();
  const { can } = useAuth();
  const [rows, setRows] = useState<Deployment[] | null>(null);
  const load = useCallback(() => api<Deployment[]>(`/api/websites/${site.id}/deployments`).then(setRows), [site.id]);
  useEffect(() => { load(); }, [load]);
  const rollback = async (d: Deployment) => {
    try { await api(`/api/websites/${site.id}/rollback/${d.id}`, { method: "POST" }); toast({ title: `Rolled back to v${d.version}`, level: "success" }); load(); onChange(); }
    catch (e: any) { toast({ title: "Rollback failed", message: e.message, level: "error" }); }
  };
  if (!rows) return <Spinner />;
  if (!rows.length) return <Empty icon={History} title="No deployments yet" />;
  return (
    <div className="space-y-3">
      {rows.map((d, i) => (
        <motion.div key={d.id} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.04 }} className="glass flex flex-wrap items-center gap-4 p-4">
          <div className="grid h-11 w-11 place-items-center rounded-xl bg-slate-100 font-display font-bold">v{d.version}</div>
          <div className="min-w-0 flex-1"><div className="flex items-center gap-2"><StatusBadge status={d.status} /><span className="text-xs text-slate-500">{d.provider} · {timeAgo(d.created_at)}</span></div>
            <p className="mt-1 truncate font-mono text-xs text-slate-500">{d.url}</p></div>
          {d.quality_score != null && <span className="text-sm text-slate-600">QA {d.quality_score}</span>}
          {can("operator") && d.id !== site.current_deployment_id && d.status !== "failed" && <Button size="sm" variant="ghost" onClick={() => rollback(d)}><RotateCcw className="h-3.5 w-3.5" /> Roll back</Button>}
          {d.id === site.current_deployment_id && <span className="chip border-emerald-500/30 text-emerald-700">serving traffic</span>}
        </motion.div>
      ))}
    </div>
  );
}

function CodeView({ site }: { site: Website }) {
  const [files, setFiles] = useState<string[] | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [content, setContent] = useState("");
  useEffect(() => { api<{ files: string[] }>(`/api/websites/${site.id}/files`).then((r) => { setFiles(r.files); if (r.files[0]) setSel(r.files.find((f) => f.endsWith("page.tsx") || f.endsWith("index.php")) ?? r.files[0]); }); }, [site.id]);
  useEffect(() => { if (sel) api<{ content: string }>(`/api/websites/${site.id}/files?path=${encodeURIComponent(sel)}`).then((r) => setContent(r.content)).catch((e) => setContent(`// ${e.message}`)); }, [sel, site.id]);
  if (!files) return <Spinner />;
  if (!files.length) return <Empty icon={Code2} title="No source generated yet" />;
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
      <div className="glass max-h-[70vh] overflow-y-auto p-2">
        {files.map((f) => <button key={f} onClick={() => setSel(f)} className={clsx("block w-full truncate rounded-lg px-2.5 py-1.5 text-left font-mono text-xs", sel === f ? "bg-violet-500/20 text-slate-900" : "text-slate-500 hover:bg-slate-100 hover:text-slate-900")}>{f}</button>)}
      </div>
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-slate-50">
        <div className="border-b border-slate-200 px-4 py-2 font-mono text-xs text-slate-500">{sel}</div>
        <pre className="max-h-[66vh] overflow-auto p-4 font-mono text-[12px] leading-relaxed text-slate-600"><code>{content}</code></pre>
      </div>
    </div>
  );
}

function HealthTab({ site }: { site: Website }) {
  const [h, setH] = useState<any>(null);
  const [hover, setHover] = useState<any>(null);
  useEffect(() => { api(`/api/websites/${site.id}/health`).then(setH); }, [site.id]);
  if (!h) return <Spinner />;
  if (!h.checks.length) return <Empty icon={Power} title="No health checks yet" text="The monitor probes every live site on a fixed interval." />;
  const max = Math.max(...h.checks.map((c: any) => c.response_ms ?? 0), 50);
  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-3">
        <Card><p className="text-xs uppercase text-slate-500">Uptime (sampled)</p><p className="mt-1 font-display text-3xl font-bold">{h.uptime_percent}%</p></Card>
        <Card><p className="text-xs uppercase text-slate-500">SSL expires</p><p className="mt-1 text-lg">{h.monitoring?.ssl_expires_at?.slice(0, 10) ?? "n/a (HTTP)"}</p></Card>
        <Card><p className="text-xs uppercase text-slate-500">Domain expires</p><p className="mt-1 text-lg">{h.monitoring?.domain_expires_at?.slice(0, 10) ?? "n/a"}</p></Card>
      </div>
      <Card>
        <div className="mb-3 flex items-baseline justify-between"><h3 className="font-display font-semibold">Response time</h3><p className="text-xs text-slate-500">{hover ? `${new Date(hover.checked_at).toLocaleTimeString()} · ${hover.ok ? `${hover.response_ms} ms` : hover.error ?? `HTTP ${hover.status_code}`}` : `last ${h.checks.length} checks`}</p></div>
        <div className="flex h-32 items-end gap-[2px]" onMouseLeave={() => setHover(null)}>
          {h.checks.map((c: any, i: number) => (
            <div key={i} onMouseEnter={() => setHover(c)} className="flex h-full flex-1 cursor-crosshair items-end" aria-label={`${c.ok ? "up" : "down"} ${c.response_ms ?? ""} ms`}>
              <div className={clsx("w-full rounded-t-[3px] transition-opacity", c.ok ? "bg-cyan-400" : "bg-rose-500", hover && hover !== c && "opacity-40")} style={{ height: `${c.ok ? Math.max(4, ((c.response_ms ?? 0) / max) * 100) : 100}%` }} />
            </div>
          ))}
        </div>
        <div className="mt-2 flex gap-4 text-[11px] text-slate-500"><span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-cyan-400" /> up (ms)</span><span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-rose-500" /> down</span></div>
      </Card>
    </div>
  );
}

function Submissions({ site }: { site: Website }) {
  const [rows, setRows] = useState<any[] | null>(null);
  useEffect(() => { api(`/api/websites/${site.id}/submissions`).then(setRows); }, [site.id]);
  if (!rows) return <Spinner />;
  if (!rows.length) return <Empty icon={Inbox} title="No form submissions yet" text="Messages sent through the generated contact form appear here." />;
  return <div className="space-y-3">{rows.map((r) => <Card key={r.id}><p className="text-sm font-medium text-slate-900">{r.data.name} <span className="text-slate-500">&lt;{r.data.email}&gt;</span></p><p className="mt-1 text-sm text-slate-600">{r.data.message}</p><p className="mt-2 text-xs text-slate-500">{timeAgo(r.created_at)}</p></Card>)}</div>;
}

function SiteSettings({ site, onSaved }: { site: Website; onSaved: () => void }) {
  const toast = useToast();
  const { can } = useAuth();
  const [f, setF] = useState({ name: site.name, domain: site.domain ?? "", require_approval: site.require_approval });
  const [env, setEnv] = useState(Object.entries(site.env ?? {}).map(([k, v]) => `${k}=${v}`).join("\n"));
  const [err, setErr] = useState<any>(null);
  const save = async () => {
    setErr(null);
    try {
      const envObj = Object.fromEntries(env.split("\n").map((l) => l.trim()).filter((l) => l.includes("=")).map((l) => [l.slice(0, l.indexOf("=")), l.slice(l.indexOf("=") + 1)]));
      await api(`/api/websites/${site.id}`, { method: "PATCH", json: { name: f.name, domain: f.domain || null, require_approval: f.require_approval, env: envObj } });
      toast({ title: "Settings saved", message: "Redeploy to apply domain changes.", level: "success" });
      onSaved();
    } catch (e) { setErr(e); }
  };
  return (
    <Card className="max-w-2xl space-y-4">
      <div><label className="label" htmlFor="sn">Name</label><input id="sn" className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} disabled={!can("operator")} /></div>
      <div><label className="label" htmlFor="sd">Domain</label><input id="sd" className="input" value={f.domain} onChange={(e) => setF({ ...f, domain: e.target.value })} placeholder="example.com" disabled={!can("operator")} /></div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.require_approval} onChange={(e) => setF({ ...f, require_approval: e.target.checked })} /> Require approval before publishing</label>
      <div><label className="label" htmlFor="se">Environment variables (non-secret, KEY=value)</label><textarea id="se" rows={4} className="input font-mono" value={env} onChange={(e) => setEnv(e.target.value)} /></div>
      <div className="grid grid-cols-2 gap-3 text-xs text-slate-500"><p>Slug: <span className="font-mono text-slate-600">{site.slug}</span></p><p>Hosting: {site.hosting_provider}</p><p>DNS: {site.dns_provider}</p><p>Created: {new Date(site.created_at).toLocaleString()}</p></div>
      <ErrorBox error={err} />
      {can("operator") && <Button onClick={save}>Save settings</Button>}
    </Card>
  );
}

function DeleteModal({ open, onClose, site, onDeleted }: { open: boolean; onClose: () => void; site: Website; onDeleted: () => void }) {
  const [text, setText] = useState("");
  const [err, setErr] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try { await api(`/api/websites/${site.id}`, { method: "DELETE", json: { confirm: text } }); onDeleted(); } catch (e) { setErr(e); setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title="Delete website permanently">
      <p className="text-sm text-slate-600">This removes the website, its deployments, artefacts, logs and history. This cannot be undone. Consider archiving instead.</p>
      <label className="label mt-4" htmlFor="confirm">Type <span className="font-mono normal-case text-rose-700">{site.slug}</span> to confirm</label>
      <input id="confirm" className="input" value={text} onChange={(e) => setText(e.target.value)} autoComplete="off" />
      <div className="mt-3"><ErrorBox error={err} /></div>
      <div className="mt-5 flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="danger" disabled={text !== site.slug} loading={busy} onClick={go}><Trash2 className="h-4 w-4" /> Delete</Button></div>
    </Modal>
  );
}
