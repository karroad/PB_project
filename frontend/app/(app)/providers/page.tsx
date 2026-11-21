"use client";

import { motion } from "framer-motion";
import { KeyRound, Plug, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useToast } from "@/components/toast";
import { Button, Card, Empty, ErrorBox, Modal, PageHeader, Spinner, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { ProviderAccount, ProviderInfo } from "@/lib/types";

export default function ProvidersPage() {
  const toast = useToast();
  const { can } = useAuth();
  const [rows, setRows] = useState<ProviderAccount[] | null>(null);
  const [catalog, setCatalog] = useState<ProviderInfo[]>([]);
  const [open, setOpen] = useState(false);
  const load = useCallback(() => api<ProviderAccount[]>("/api/providers").then(setRows).catch(() => setRows([])), []);
  useEffect(() => { load(); api<ProviderInfo[]>("/api/providers/catalog").then(setCatalog); }, [load]);

  const test = async (p: ProviderAccount) => {
    try { const r = await api(`/api/providers/${p.id}/test`, { method: "POST" }); toast({ title: r.ok ? "Connection OK" : "Connection failed", message: r.message, level: r.ok ? "success" : "error" }); load(); }
    catch (e: any) { toast({ title: "Test failed", message: e.message, level: "error" }); }
  };
  const remove = async (p: ProviderAccount) => {
    if (!confirm(`Remove ${p.label}? Credentials will be deleted.`)) return;
    try { await api(`/api/providers/${p.id}`, { method: "DELETE" }); load(); } catch (e: any) { toast({ title: "Cannot remove", message: e.message, level: "error" }); }
  };

  return (
    <div>
      <PageHeader title="Provider accounts" subtitle="Hosting, DNS, registrar, commerce and AI credentials — encrypted at rest, never exposed to generated sites."
        actions={can("admin") && <Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Connect account</Button>} />
      <div className="mb-6 flex items-center gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.06] px-4 py-3 text-xs text-emerald-700"><ShieldCheck className="h-4 w-4" /> Secrets are Fernet-encrypted, masked in the UI, and scanned for leaks in every build before deployment.</div>
      {!rows ? <Spinner /> : !rows.length ? <Empty icon={Plug} title="No accounts connected" text="Local hosting works without any accounts. Connect Cloudflare or OVH (domains), Hetzner (servers) or Fal.ai (images) when you're ready." /> : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {rows.map((p, i) => (
            <motion.div key={p.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}>
              <Card>
                <div className="flex items-start justify-between"><div><p className="text-xs uppercase tracking-wider text-slate-500">{p.kind} · {p.provider}</p><h3 className="font-display text-lg font-semibold">{p.label}</h3></div><StatusBadge status={p.status} /></div>
                <div className="mt-3 space-y-1">{Object.entries(p.credentials).map(([k, v]) => <p key={k} className="flex justify-between font-mono text-[11px]"><span className="text-slate-500">{k}</span><span className="text-slate-600">{v}</span></p>)}</div>
                <p className="mt-3 text-xs text-slate-500">Sites: {p.used_sites} / {p.max_sites ?? "∞"}</p>
                {can("admin") && <div className="mt-4 flex gap-2"><Button size="sm" variant="ghost" onClick={() => test(p)}>Test connection</Button><Button size="sm" variant="subtle" onClick={() => remove(p)} aria-label="Remove"><Trash2 className="h-3.5 w-3.5" /></Button></div>}
              </Card>
            </motion.div>
          ))}
        </div>
      )}
      <AddModal open={open} onClose={() => setOpen(false)} catalog={catalog} onSaved={() => { setOpen(false); load(); }} />
    </div>
  );
}

function AddModal({ open, onClose, catalog, onSaved }: { open: boolean; onClose: () => void; catalog: ProviderInfo[]; onSaved: () => void }) {
  const [provider, setProvider] = useState("");
  const [label, setLabel] = useState("");
  const [limit, setLimit] = useState("");
  const [creds, setCreds] = useState<Record<string, string>>({});
  const [err, setErr] = useState<any>(null);
  const info = catalog.find((c) => c.key === provider);
  useEffect(() => { if (!provider && catalog[0]) setProvider(catalog[0].key); }, [catalog, provider]);
  const save = async () => {
    setErr(null);
    try {
      await api("/api/providers", { method: "POST", json: { provider, kind: info?.kind, label: label || info?.name, credentials: creds, max_sites: limit ? Number(limit) : null } });
      setCreds({}); setLabel(""); setLimit(""); onSaved();
    } catch (e) { setErr(e); }
  };
  return (
    <Modal open={open} onClose={onClose} title="Connect provider account">
      <div className="space-y-3">
        <div><label className="label" htmlFor="pp">Provider</label><select id="pp" className="input" value={provider} onChange={(e) => { setProvider(e.target.value); setCreds({}); }}>{catalog.map((c) => <option key={c.key} value={c.key}>{c.name} ({c.kind})</option>)}</select>
          {info && <p className="mt-1 text-xs text-slate-500">{info.description}</p>}</div>
        <div><label className="label" htmlFor="pl">Label</label><input id="pl" className="input" value={label} onChange={(e) => setLabel(e.target.value)} placeholder={info?.name} /></div>
        {info?.credential_fields?.map((f) => (
          <div key={f}><label className="label" htmlFor={f}><KeyRound className="mr-1 inline h-3 w-3" />{f.replace(/_/g, " ")}</label>
            <input id={f} className="input font-mono" type={/token|secret|key/.test(f) && !f.endsWith("name") && !f.endsWith("path") ? "password" : "text"} value={creds[f] ?? ""} onChange={(e) => setCreds({ ...creds, [f]: e.target.value })} autoComplete="off" /></div>
        ))}
        <div><label className="label" htmlFor="lim">Max websites on this account (verify your plan)</label><input id="lim" className="input" type="number" min={1} value={limit} onChange={(e) => setLimit(e.target.value)} placeholder="Unlimited" /></div>
        <ErrorBox error={err} />
        <div className="flex justify-end gap-2 pt-2"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button onClick={save}>Save encrypted</Button></div>
      </div>
    </Modal>
  );
}
