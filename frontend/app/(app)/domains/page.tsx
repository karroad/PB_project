"use client";

import clsx from "clsx";
import { motion } from "framer-motion";
import { Check, Globe2, RefreshCw, RotateCcw, ShoppingCart } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { usePlatformEvents } from "@/components/Shell";
import { useToast } from "@/components/toast";
import { Button, Card, Empty, ErrorBox, PageHeader, Spinner } from "@/components/ui";
import { api, timeAgo } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Catalog, DomainQuote, DomainRecord, ProviderAccount } from "@/lib/types";

const STATUS: Record<string, { label: string; cls: string; hint?: string }> = {
  quoted: { label: "Quoted", cls: "bg-slate-500/10 text-slate-600 border-slate-500/20", hint: "Price checked, not bought yet" },
  ordering: { label: "Ordering", cls: "bg-violet-500/10 text-violet-700 border-violet-500/30" },
  pending: { label: "Activating", cls: "bg-cyan-500/10 text-cyan-700 border-cyan-500/30", hint: "Order placed, waiting for the registry" },
  active: { label: "Active", cls: "bg-emerald-500/10 text-emerald-700 border-emerald-500/30" },
  failed: { label: "Failed", cls: "bg-rose-500/10 text-rose-700 border-rose-500/30", hint: "Nothing was charged" },
  unknown: { label: "Needs check", cls: "bg-amber-500/10 text-amber-700 border-amber-500/30", hint: "Check the provider dashboard, then Sync or Reset" },
};

export default function DomainsPage() {
  const toast = useToast();
  const { can } = useAuth();
  const [rows, setRows] = useState<DomainRecord[] | null>(null);
  const [busy, setBusy] = useState("");
  const load = useCallback(() => api<DomainRecord[]>("/api/domains").then(setRows).catch(() => setRows([])), []);
  useEffect(() => { load(); }, [load]);
  usePlatformEvents((ev) => { if (ev.type === "domain") load(); });

  const act = async (d: DomainRecord, op: "sync" | "reset") => {
    if (op === "reset" && !confirm(`Confirm that ${d.name} was NOT bought at ${d.provider}. The platform may then try to buy it again.`)) return;
    setBusy(d.id + op);
    try {
      const r = await api<DomainRecord>(`/api/domains/${d.id}/${op}`, { method: "POST" });
      toast({ title: op === "sync" ? `${d.name}: ${STATUS[r.status]?.label ?? r.status}` : `${d.name} reset — resume the website's job to buy it`, level: "success" });
      load();
    } catch (e: any) { toast({ title: "Action failed", message: e.message, level: "error" }); }
    finally { setBusy(""); }
  };

  return (
    <div>
      <PageHeader title="Domains" subtitle="Domains bought through Cloudflare or OVH. Each purchase is recorded so a domain is never ordered twice." />
      <BuyDomain onBought={load} />
      {!rows ? <Spinner /> : !rows.length ? (
        <Empty icon={Globe2} title="No domains bought yet" text="Search and buy one above, or choose a domain provider when creating a website."
          action={<Link href="/new"><Button>Create website</Button></Link>} />
      ) : (
        <div className="glass overflow-x-auto p-0">
          <table className="w-full min-w-[820px] text-sm">
            <thead><tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wider text-slate-500"><th className="p-4">Domain</th><th>Status</th><th>Provider</th><th>Price</th><th>Expires</th><th>Website</th><th /></tr></thead>
            <tbody>
              {rows.map((d, i) => {
                const s = STATUS[d.status] ?? { label: d.status, cls: "bg-slate-500/10 text-slate-600 border-slate-500/20" };
                return (
                  <motion.tr key={d.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: Math.min(i, 20) * 0.02 }} className="border-b border-slate-200 align-top">
                    <td className="p-4"><p className="font-mono text-slate-900">{d.name}</p>{d.error && <p className="mt-1 max-w-xs text-xs text-rose-700">{d.error}</p>}<p className="mt-1 text-[11px] text-slate-500">added {timeAgo(d.created_at)}</p></td>
                    <td className="pt-4"><span className={`inline-flex rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${s.cls}`} title={s.hint}>{s.label}</span>{s.hint && <p className="mt-1 max-w-[180px] text-[11px] text-slate-500">{s.hint}</p>}</td>
                    <td className="pt-4 capitalize text-slate-600">{d.provider}</td>
                    <td className="pt-4 text-slate-600">{d.price != null ? `${d.price.toFixed(2)} ${d.currency ?? ""}` : "—"}<p className="text-[11px] text-slate-500">{d.years}y · auto-renew {d.auto_renew ? "on" : "off"}</p></td>
                    <td className="pt-4 text-xs text-slate-500">{d.expires_at?.slice(0, 10) ?? "—"}</td>
                    <td className="pt-4">{d.website_id ? <Link href={`/sites/${d.website_id}`} className="text-cyan-700 hover:underline">{d.website_name ?? "open"}</Link> : "—"}</td>
                    <td className="pr-4 pt-3 text-right">
                      {can("operator") && d.status !== "active" && <Button size="sm" variant="ghost" loading={busy === d.id + "sync"} onClick={() => act(d, "sync")}><RefreshCw className="h-3.5 w-3.5" /> Sync</Button>}
                      {can("admin") && ["unknown", "failed"].includes(d.status) && <Button size="sm" variant="subtle" className="ml-1" loading={busy === d.id + "reset"} onClick={() => act(d, "reset")}><RotateCcw className="h-3.5 w-3.5" /> Reset</Button>}
                    </td>
                  </motion.tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function BuyDomain({ onBought }: { onBought: () => void }) {
  const toast = useToast();
  const { can } = useAuth();
  const [cat, setCat] = useState<Catalog | null>(null);
  const [accounts, setAccounts] = useState<ProviderAccount[]>([]);
  const [provider, setProvider] = useState("");
  const [accountId, setAccountId] = useState("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState<{ loading?: boolean; error?: string; results?: DomainQuote[] } | null>(null);
  const [chosen, setChosen] = useState("");
  const [buying, setBuying] = useState(false);
  const [error, setError] = useState<any>(null);

  useEffect(() => {
    api<Catalog>("/api/catalog").then(setCat).catch(() => {});
    api<ProviderAccount[]>("/api/providers").then(setAccounts).catch(() => {});
  }, []);

  const registrars = (cat?.dns ?? []).filter((d) => d.can_register && d.enabled !== false);
  const providerAccounts = accounts.filter((a) => a.provider === provider);
  const quote = search?.results?.find((r) => r.domain === chosen);

  const runSearch = async () => {
    if (!query.trim() || !provider || !accountId) return;
    setSearch({ loading: true }); setError(null);
    try { setSearch(await api<{ results: DomainQuote[] }>(`/api/domains/search?q=${encodeURIComponent(query)}&provider=${provider}&account_id=${accountId}`)); }
    catch (e: any) { setSearch({ error: e.message }); }
  };

  const buy = async () => {
    if (!chosen) return;
    setBuying(true); setError(null);
    try {
      await api(`/api/domains/buy`, { method: "POST", json: { domain: chosen, provider, account_id: accountId } });
      toast({ title: `${chosen} purchased`, message: "Attach it to a website from the Publish step (“Use one I own”).", level: "success" });
      setChosen(""); setSearch(null); setQuery(""); onBought();
    } catch (e) { setError(e); } finally { setBuying(false); }
  };

  if (!can("admin")) return null;
  return (
    <Card className="mb-6">
      <h3 className="mb-1 font-display font-semibold">Buy a domain</h3>
      <p className="mb-4 text-sm text-slate-500">Buy a domain directly, then attach it to any website from its Publish step (“Use one I own”).</p>
      {!registrars.length ? (
        <p className="text-sm text-slate-500">No domain registrar connected yet. <Link href="/providers" className="font-medium text-violet-700 underline">Connect Cloudflare or OVH under Providers</Link>.</p>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="buy-provider">Registrar</label>
              <select id="buy-provider" className="input" value={provider}
                onChange={(e) => { setProvider(e.target.value); setAccountId(accounts.find((a) => a.provider === e.target.value)?.id ?? ""); setSearch(null); setChosen(""); }}>
                <option value="">Choose a registrar…</option>
                {registrars.map((d) => <option key={d.key} value={d.key}>{d.name}</option>)}
              </select>
            </div>
            <div>
              <label className="label" htmlFor="buy-account">Account</label>
              {providerAccounts.length ? (
                <select id="buy-account" className="input" value={accountId} onChange={(e) => { setAccountId(e.target.value); setSearch(null); }}>
                  <option value="">Select an account…</option>
                  {providerAccounts.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
                </select>
              ) : <p className="rounded-xl border border-amber-300 bg-amber-50 px-3 py-2.5 text-xs text-amber-800">No account for this registrar yet. <Link href="/providers" className="font-medium underline">Connect one under Providers</Link>.</p>}
            </div>
          </div>
          <div className="mt-3 flex gap-2">
            <input className="input" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && runSearch()}
              placeholder="Search a name or domain" aria-label="Domain search" disabled={!provider || !accountId} />
            <Button variant="ghost" className="shrink-0 whitespace-nowrap" onClick={runSearch} disabled={!provider || !accountId || !query.trim()} loading={search?.loading}>Search</Button>
          </div>
          {search?.error && <p className="mt-2 text-xs text-rose-600">{search.error}</p>}
          {search?.results && (
            <ul className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {search.results.map((r) => (
                <li key={r.domain}>
                  <button disabled={!r.buyable} onClick={() => setChosen(r.domain)} aria-pressed={chosen === r.domain}
                    className={clsx("flex w-full items-center gap-2 rounded-xl border px-3 py-2 text-left transition disabled:cursor-not-allowed",
                      chosen === r.domain ? "border-emerald-500 bg-emerald-50" : r.buyable ? "border-slate-200 bg-white hover:border-slate-300" : "border-slate-100 bg-white opacity-50")}>
                    <span className="min-w-0 flex-1 truncate font-mono text-sm text-slate-900">{r.domain}</span>
                    {r.buyable ? <span className="text-sm font-semibold text-emerald-700">{r.price?.toFixed(2)} {r.currency}</span>
                      : <span className="text-[11px] text-slate-500">{r.in_use ? "in use" : !r.available ? (r.premium ? "premium" : "taken") : "over limit"}</span>}
                    {chosen === r.domain && <Check className="h-4 w-4 text-emerald-600" />}
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-3"><ErrorBox error={error} /></div>
          <div className="mt-4 flex items-center justify-between gap-3">
            <p className="text-xs text-slate-500">{quote ? <>Buying <span className="font-mono text-slate-800">{quote.domain}</span> for {quote.price?.toFixed(2)} {quote.currency}/yr — charged immediately.</> : "Pick an available domain above."}</p>
            <Button onClick={buy} loading={buying} disabled={!chosen}><ShoppingCart className="h-4 w-4" /> Buy now</Button>
          </div>
        </>
      )}
    </Card>
  );
}
