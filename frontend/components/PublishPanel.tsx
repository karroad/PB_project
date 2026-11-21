"use client";

import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import { Check, Globe, Rocket, Search, ShoppingCart } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Catalog, DomainQuote, Job, ProviderAccount, Website } from "@/lib/types";
import { Button, ErrorBox } from "./ui";

/** Publish step: choose hosting + domain provider (buy a new domain or use one you own), then go live. */
export function PublishPanel({ site, onPublished, onCancel }: { site: Website; onPublished: (job: Job) => void; onCancel?: () => void }) {
  const [cat, setCat] = useState<Catalog | null>(null);
  const [accounts, setAccounts] = useState<ProviderAccount[]>([]);
  const [f, setF] = useState({
    hosting_provider: site.hosting_provider || "local", hosting_account_id: site.hosting_account_id || "",
    dns_provider: site.dns_provider && site.dns_provider !== "none" ? site.dns_provider : "", dns_account_id: site.dns_account_id || "",
    domain: site.domain || "", domain_mode: (site.domain_mode as "buy" | "existing") || "buy",
  });
  const [query, setQuery] = useState(site.name);
  const [search, setSearch] = useState<{ loading?: boolean; error?: string; results?: DomainQuote[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<any>(null);
  const set = (k: string, v: any) => setF((x) => ({ ...x, [k]: v }));

  useEffect(() => {
    api<Catalog>("/api/catalog").then(setCat).catch(setError);
    api<ProviderAccount[]>("/api/providers").then(setAccounts).catch(() => {});
  }, []);

  const policy = cat?.policy;
  const hosting = cat?.hosting.find((h) => h.key === f.hosting_provider);
  const dnsInfo = cat?.dns.find((d) => d.key === f.dns_provider);
  const dnsAccounts = accounts.filter((a) => a.provider === f.dns_provider);
  const custom = !!f.dns_provider && f.dns_provider !== "none";
  const buying = custom && f.domain_mode === "buy";
  const quote = search?.results?.find((r) => r.domain === f.domain);
  const missing = [
    !f.dns_provider && "a domain provider",
    custom && !f.dns_account_id && `a ${dnsInfo?.name ?? ""} account`,
    custom && !f.domain.trim() && (buying ? "a domain to buy (search and pick one)" : "the domain name"),
    buying && policy && !policy.public_server && f.hosting_provider !== "hetzner" && "a public server (set SERVER_PUBLIC_IP or choose Hetzner)",
    hosting?.external && !f.hosting_account_id && `a ${hosting.name} account`,
  ].filter(Boolean) as string[];

  const runSearch = async () => {
    if (!query.trim() || !f.dns_account_id) return;
    setSearch({ loading: true });
    try {
      const r = await api<{ results: DomainQuote[] }>(`/api/domains/search?q=${encodeURIComponent(query)}&provider=${f.dns_provider}&account_id=${f.dns_account_id}`);
      setSearch(r);
      const first = r.results.find((x) => x.buyable);
      if (first) set("domain", first.domain);
    } catch (e: any) { setSearch({ error: e.message }); }
  };

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const job = await api<Job>(`/api/websites/${site.id}/publish`, { method: "POST", json: {
        hosting_provider: f.hosting_provider, hosting_account_id: f.hosting_account_id || null, dns_provider: f.dns_provider,
        dns_account_id: custom ? f.dns_account_id || null : null, domain: custom ? f.domain.trim() || null : null, domain_mode: custom ? f.domain_mode : null } });
      onPublished(job);
    } catch (e) { setError(e); setBusy(false); }
  };

  return (
    <div className="space-y-6">
      <section>
        <h3 className="mb-3 text-sm font-semibold text-slate-900">Where should it run?</h3>
        <div className="grid gap-2 sm:grid-cols-3">
          {cat?.hosting.filter((h) => h.enabled !== false).map((h) => (
            <Choice key={h.key} active={f.hosting_provider === h.key} onClick={() => set("hosting_provider", h.key)} title={h.name} text={h.description} badge={h.requires_approval ? "approval" : undefined} />
          ))}
        </div>
        {hosting?.external && (
          <select className="input mt-3" value={f.hosting_account_id} onChange={(e) => set("hosting_account_id", e.target.value)} aria-label="Hosting account">
            <option value="">Select a {hosting.name} account…</option>
            {accounts.filter((a) => a.provider === hosting.key).map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
          </select>
        )}
      </section>

      <section>
        <h3 className="mb-3 text-sm font-semibold text-slate-900">Domain provider</h3>
        <div className="grid gap-2 sm:grid-cols-2">
          {cat?.dns.map((d) => (
            <Choice key={d.key} active={f.dns_provider === d.key} disabled={d.enabled === false} title={d.name}
              badge={d.enabled === false ? "planned" : undefined} text={d.enabled === false ? d.disabled_reason || d.description : d.description}
              onClick={() => { setF((x) => ({ ...x, dns_provider: d.key, dns_account_id: accounts.find((a) => a.provider === d.key)?.id ?? "", domain: d.key === "none" ? "" : x.domain })); setSearch(null); }} />
          ))}
        </div>
        <AnimatePresence>
          {custom && (
            <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="label" htmlFor="pacc">{dnsInfo?.name} account</label>
                  {dnsAccounts.length ? (
                    <select id="pacc" className="input" value={f.dns_account_id} onChange={(e) => { set("dns_account_id", e.target.value); setSearch(null); }}>
                      <option value="">Select an account…</option>
                      {dnsAccounts.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
                    </select>
                  ) : <p className="rounded-xl border border-amber-300 bg-amber-50 px-3 py-2.5 text-xs text-amber-800">No {dnsInfo?.name} account yet. <Link href="/providers" className="font-medium underline">Connect one under Providers</Link>.</p>}
                </div>
                <div>
                  <span className="label">Domain</span>
                  <div className="flex gap-1 rounded-xl border border-slate-200 bg-slate-50 p-1" role="radiogroup" aria-label="Domain option">
                    {([["buy", "Buy a new domain", ShoppingCart], ["existing", "Use one I own", Globe]] as const).map(([k, label, I]) => (
                      <button key={k} role="radio" aria-checked={f.domain_mode === k} onClick={() => setF((x) => ({ ...x, domain_mode: k, domain: "" }))}
                        className={clsx("flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition", f.domain_mode === k ? "bg-white text-violet-700 shadow-sm" : "text-slate-500 hover:text-slate-900")}>
                        <I className="h-3.5 w-3.5" />{label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              {buying ? (
                <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50/60 p-3">
                  <div className="flex gap-2">
                    <input className="input" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && runSearch()} placeholder="Search a name or domain" aria-label="Domain search" />
                    <Button variant="ghost" className="shrink-0 whitespace-nowrap" onClick={runSearch} disabled={!f.dns_account_id || !query.trim()} loading={search?.loading}><Search className="h-4 w-4" /> Search</Button>
                  </div>
                  {search?.error && <p className="mt-2 text-xs text-rose-600">{search.error}</p>}
                  {search?.results && (
                    <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                      {search.results.map((r) => (
                        <li key={r.domain}>
                          <button disabled={!r.buyable} onClick={() => set("domain", r.domain)} aria-pressed={f.domain === r.domain}
                            className={clsx("flex w-full items-center gap-2 rounded-xl border px-3 py-2 text-left transition disabled:cursor-not-allowed",
                              f.domain === r.domain ? "border-emerald-500 bg-emerald-50" : r.buyable ? "border-slate-200 bg-white hover:border-slate-300" : "border-slate-100 bg-white opacity-50")}>
                            <span className="min-w-0 flex-1 truncate font-mono text-sm text-slate-900">{r.domain}</span>
                            {r.buyable ? <span className="text-sm font-semibold text-emerald-700">{r.price?.toFixed(2)} {r.currency}</span>
                              : <span className="text-[11px] text-slate-500">{r.in_use ? "in use" : !r.available ? (r.premium ? "premium" : "taken") : "over limit"}</span>}
                            {f.domain === r.domain && <Check className="h-4 w-4 text-emerald-600" />}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                  <p className="mt-3 text-xs text-slate-500">
                    {policy?.sandbox && <span className="mr-1 rounded bg-amber-100 px-1.5 py-0.5 font-medium text-amber-800">SANDBOX: simulated, no charge</span>}
                    {quote ? <>Buying <span className="font-mono text-slate-800">{quote.domain}</span> for {quote.price?.toFixed(2)} {quote.currency}/yr. </> : null}
                    Limit {policy?.domain_max_price} per domain · auto-renew {policy?.domain_auto_renew ? "on" : "off"}
                    {policy?.approval_domain_purchase ? " · an admin confirms the purchase before it's charged." : "."}
                  </p>
                </div>
              ) : (
                <input className="input mt-3" placeholder="example.com" value={f.domain} onChange={(e) => set("domain", e.target.value)} aria-label="Domain you own" />
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </section>

      <ErrorBox error={error} />
      <div className="flex flex-col gap-3 border-t border-slate-200 pt-4 sm:flex-row sm:items-center">
        <p className={clsx("flex-1 text-sm", missing.length ? "text-amber-700" : "text-slate-500")}>
          {missing.length ? `Still needed: ${missing.join(", ")}.` : site.status === "live" ? "Your reviewed changes will replace the live version (the old one stays available for rollback)." : "The reviewed preview goes live."}
        </p>
        {onCancel && <Button variant="ghost" onClick={onCancel}>Cancel</Button>}
        <Button onClick={submit} loading={busy} disabled={missing.length > 0}><Rocket className="h-4 w-4" /> {site.status === "live" ? "Publish changes" : "Publish website"}</Button>
      </div>
    </div>
  );
}

function Choice({ active, disabled, onClick, title, text, badge }: { active: boolean; disabled?: boolean; onClick: () => void; title: string; text: string; badge?: string }) {
  return (
    <button onClick={onClick} disabled={disabled} aria-pressed={active}
      className={clsx("rounded-xl border p-3 text-left transition disabled:cursor-not-allowed disabled:opacity-40",
        active ? "border-violet-500 bg-violet-50 ring-2 ring-violet-500/15" : "border-slate-200 bg-white hover:border-slate-300")}>
      <div className="flex items-center gap-2">
        <p className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-900">{title}</p>
        {badge && <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] capitalize text-slate-600">{badge}</span>}
        {active && <Check className="h-4 w-4 text-violet-600" />}
      </div>
      <p className="mt-1 line-clamp-2 text-xs text-slate-500">{text}</p>
    </button>
  );
}
