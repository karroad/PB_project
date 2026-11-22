"use client";

import clsx from "clsx";
import { motion } from "framer-motion";
import { AlertTriangle, Check, Copy, Cpu, HardDrive, KeyRound, MemoryStick, Network, Plug, Plus, RefreshCw, Server as ServerIcon, Settings2, ShieldCheck, Trash2, Wrench } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useToast } from "@/components/toast";
import { Button, Card, Empty, ErrorBox, Modal, PageHeader, Spinner, StatusBadge } from "@/components/ui";
import { api, timeAgo } from "@/lib/api";
import { useAuth } from "@/lib/auth";

interface SSHKey { id: string; name: string; public_key: string; fingerprint: string; key_type: string; used_by: number; created_at: string }
interface ServerRow {
  id: string; name: string; provider: string; host: string; port: number; username: string; ssh_key_id: string | null; ssh_key_name: string | null;
  base_dir: string; simulated: boolean; status: string; os_info: string | null; web_server: string | null; metrics: any; max_sites: number | null;
  error: string | null; host_key_pinned: boolean; last_checked_at: string | null; sites: { id: string; name: string; status: string; domain: string | null; url: string | null }[];
  web_config: TraefikConfig | null; web_overrides: Partial<Record<TraefikKey, string>>; web_conflict: boolean;
}
type TraefikKey = "network" | "entrypoint" | "http_entrypoint" | "certresolver";
interface TraefikConfig extends Partial<Record<TraefikKey, string>> {
  container?: string; networks?: string[]; entrypoints?: string[]; certresolvers?: string[]; routed_containers?: number;
}

const PROVIDERS: Record<string, string> = { hetzner: "Hetzner", ovh: "OVHcloud", hostinger: "Hostinger", other: "Other" };

export default function ServersPage() {
  const toast = useToast();
  const { can } = useAuth();
  const [tab, setTab] = useState<"servers" | "keys">("servers");
  const [servers, setServers] = useState<ServerRow[] | null>(null);
  const [keys, setKeys] = useState<SSHKey[] | null>(null);
  const [addServer, setAddServer] = useState(false);
  const [addKey, setAddKey] = useState(false);
  const [busy, setBusy] = useState("");
  const [sandbox, setSandbox] = useState(false);
  const [editTraefik, setEditTraefik] = useState<ServerRow | null>(null);

  const load = useCallback(async () => {
    const [s, k] = await Promise.all([api<ServerRow[]>("/api/servers").catch(() => []), api<SSHKey[]>("/api/ssh-keys").catch(() => [])]);
    setServers(s); setKeys(k);
  }, []);
  useEffect(() => { load(); api<{ sandbox?: boolean }>("/api/health").then((h) => setSandbox(!!h.sandbox)).catch(() => {}); }, [load]);

  const act = async (id: string, op: "test" | "provision" | "refresh", label: string) => {
    setBusy(id + op);
    try {
      const r = await api<any>(`/api/servers/${id}/${op}`, { method: "POST" });
      if (op === "test" && r.ok === false) toast({ title: "Connection failed", message: [r.error, r.hint].filter(Boolean).join(" — "), level: "error" });
      else toast({ title: label, level: "success" });
      load();
    } catch (e: any) { toast({ title: `${label} failed`, message: e.message, level: "error" }); load(); }
    finally { setBusy(""); }
  };
  const remove = async (path: string, what: string) => {
    if (!confirm(`Delete ${what}?`)) return;
    try { await api(path, { method: "DELETE" }); load(); } catch (e: any) { toast({ title: "Can't delete", message: e.message, level: "error" }); }
  };

  return (
    <div>
      <PageHeader title="Servers" subtitle="Your own machines (Hetzner, OVH, Hostinger VPS…) managed over SSH. Websites are deployed to them with automatic HTTPS and instant rollback."
        actions={can("admin") && (tab === "servers"
          ? <Button onClick={() => setAddServer(true)}><Plus className="h-4 w-4" /> Add server</Button>
          : <Button onClick={() => setAddKey(true)}><Plus className="h-4 w-4" /> Add SSH key</Button>)} />

      <div className="mb-6 inline-flex rounded-xl border border-slate-200 bg-white p-1 shadow-sm" role="tablist">
        {([["servers", `Servers${servers ? ` (${servers.length})` : ""}`, ServerIcon], ["keys", `SSH keys${keys ? ` (${keys.length})` : ""}`, KeyRound]] as const).map(([k, label, I]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={clsx("flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition", tab === k ? "bg-violet-50 text-violet-700" : "text-slate-500 hover:text-slate-900")}>
            <I className="h-4 w-4" />{label}
          </button>
        ))}
      </div>

      {tab === "servers" && (!servers ? <Spinner /> : !servers.length ? (
        <Empty icon={ServerIcon} title="No servers yet" text={keys?.length ? "Add a server and the platform will connect with your SSH key, prepare it and deploy websites to it." : "Start by adding an SSH key (paste yours or generate one), then add a server."}
          action={can("admin") && <Button onClick={() => (keys?.length ? setAddServer(true) : (setTab("keys"), setAddKey(true)))}><Plus className="h-4 w-4" /> {keys?.length ? "Add server" : "Add SSH key"}</Button>} />
      ) : (
        <div className="grid gap-5 xl:grid-cols-2">
          {servers.map((s, i) => (
            <motion.div key={s.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}>
              <Card className="h-full">
                <div className="flex items-start gap-3">
                  <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-violet-50 text-violet-600"><ServerIcon className="h-5 w-5" /></div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2"><h3 className="truncate font-display text-lg font-semibold text-slate-900">{s.name}</h3><StatusBadge status={s.status} />{s.simulated && <span className="chip border-amber-200 bg-amber-50 text-amber-800">sandbox</span>}</div>
                    <p className="font-mono text-xs text-slate-500">{s.username}@{s.host}:{s.port} · {PROVIDERS[s.provider] ?? s.provider}</p>
                    <p className="text-xs text-slate-500">{s.os_info ?? "OS unknown"}{s.web_server ? ` · ${s.web_server}` : ""}{s.ssh_key_name ? ` · key: ${s.ssh_key_name}` : ""}{s.host_key_pinned ? " · host key pinned" : ""}</p>
                  </div>
                </div>
                {s.error && <div className="mt-3"><ErrorBox error={{ message: s.error }} /></div>}
                {s.web_conflict && !s.error && (
                  <p className="mt-3 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    Ports 80/443 are used by {s.web_server}. SiteForge won&apos;t install a second web server here. Use a server with Traefik or with free ports.
                  </p>
                )}
                {s.web_server === "traefik" && s.web_config && (
                  <div className="mt-3 rounded-xl border border-cyan-200 bg-cyan-50/60 px-3 py-2.5 text-xs text-slate-700">
                    <div className="flex items-center gap-2">
                      <Network className="h-3.5 w-3.5 text-cyan-700" />
                      <p className="font-semibold text-cyan-900">Existing Traefik reused</p>
                      <span className="text-slate-500">· {s.web_config.routed_containers ?? 0} other routed apps left untouched</span>
                      {can("admin") && <button onClick={() => setEditTraefik(s)} className="ml-auto inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium text-cyan-800 hover:bg-cyan-100" aria-label="Traefik settings"><Settings2 className="h-3.5 w-3.5" /> Settings</button>}
                    </div>
                    <p className="mt-1 font-mono text-[11px] text-slate-600">
                      network {s.web_config.network ?? "?"} · entrypoint {s.web_config.entrypoint ?? "?"} · certs {s.web_config.certresolver ?? "none"}
                    </p>
                  </div>
                )}
                <div className="mt-4 grid grid-cols-3 gap-2">
                  <Meter icon={Cpu} label="CPU" value={s.metrics?.cpu_percent} sub={s.metrics?.cpus ? `${s.metrics.cpus} cores · load ${s.metrics.load1}` : ""} />
                  <Meter icon={MemoryStick} label="Memory" value={s.metrics?.mem_percent} sub={s.metrics?.mem_total ? `${(s.metrics.mem_total / 1e9).toFixed(1)} GB` : ""} />
                  <Meter icon={HardDrive} label="Disk" value={s.metrics?.disk_percent} sub={s.metrics?.disk_total ? `${((s.metrics.disk_total - s.metrics.disk_used) / 1e9).toFixed(0)} GB free` : ""} />
                </div>
                <div className="mt-4">
                  <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-slate-500">Websites {s.sites.length}{s.max_sites ? ` / ${s.max_sites}` : ""}</p>
                  {s.sites.length ? (
                    <div className="flex flex-wrap gap-1.5">{s.sites.map((w) => <Link key={w.id} href={`/sites/${w.id}`} className="chip hover:border-violet-300 hover:text-violet-700">{w.domain || w.name}</Link>)}</div>
                  ) : <p className="text-xs text-slate-400">No websites yet. Choose this server when publishing.</p>}
                </div>
                <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-4">
                  <Button size="sm" variant="ghost" loading={busy === s.id + "test"} onClick={() => act(s.id, "test", "Connection OK")}><Plug className="h-3.5 w-3.5" /> Test</Button>
                  {can("admin") && <Button size="sm" variant={s.status === "ready" ? "ghost" : "primary"} loading={busy === s.id + "provision"} onClick={() => act(s.id, "provision", "Server prepared")}><Wrench className="h-3.5 w-3.5" /> {s.status === "ready" ? "Re-run setup" : "Prepare server"}</Button>}
                  <Button size="sm" variant="ghost" loading={busy === s.id + "refresh"} onClick={() => act(s.id, "refresh", "Health refreshed")}><RefreshCw className="h-3.5 w-3.5" /> Health</Button>
                  {can("admin") && s.error?.includes("Host key") && <Button size="sm" variant="danger" onClick={async () => { await api(`/api/servers/${s.id}/reset-host-key`, { method: "POST" }); load(); }}>Reset host key</Button>}
                  <span className="ml-auto text-[11px] text-slate-400">{s.last_checked_at ? `checked ${timeAgo(s.last_checked_at)}` : "not checked yet"}</span>
                  {can("admin") && <Button size="sm" variant="subtle" aria-label="Delete server" onClick={() => remove(`/api/servers/${s.id}`, `server ${s.name}`)}><Trash2 className="h-3.5 w-3.5" /></Button>}
                </div>
              </Card>
            </motion.div>
          ))}
        </div>
      ))}

      {tab === "keys" && (!keys ? <Spinner /> : !keys.length ? (
        <Empty icon={KeyRound} title="No SSH keys yet" text="Paste the private key you already use for your servers, or generate a new key and add its public key to each server."
          action={can("admin") && <Button onClick={() => setAddKey(true)}><Plus className="h-4 w-4" /> Add SSH key</Button>} />
      ) : (
        <div className="space-y-3">
          <p className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-xs text-emerald-800"><ShieldCheck className="h-4 w-4" /> Private keys are encrypted and never shown again. Only the public key below is displayed.</p>
          {keys.map((k) => (
            <Card key={k.id} className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <KeyRound className="h-5 w-5 shrink-0 text-violet-600" />
              <div className="min-w-0 flex-1">
                <p className="font-semibold text-slate-900">{k.name} <span className="text-xs font-normal text-slate-500">· {k.key_type} · used by {k.used_by} server{k.used_by === 1 ? "" : "s"}</span></p>
                <p className="truncate font-mono text-[11px] text-slate-500">{k.fingerprint}</p>
              </div>
              <CopyButton text={k.public_key} label="Copy public key" />
              {can("admin") && <Button size="sm" variant="subtle" aria-label="Delete key" onClick={() => remove(`/api/ssh-keys/${k.id}`, `key ${k.name}`)}><Trash2 className="h-3.5 w-3.5" /></Button>}
            </Card>
          ))}
        </div>
      ))}

      <AddKeyModal open={addKey} onClose={() => setAddKey(false)} onDone={() => { load(); }} />
      {editTraefik && <TraefikModal server={editTraefik} onClose={() => setEditTraefik(null)} onSaved={() => { setEditTraefik(null); load(); toast({ title: "Traefik settings saved", message: "Run Prepare again to check them.", level: "success" }); }} />}
      <AddServerModal open={addServer} onClose={() => setAddServer(false)} keys={keys ?? []} sandbox={sandbox} onDone={() => { setAddServer(false); load(); }} />
    </div>
  );
}

function Meter({ icon: Icon, label, value, sub }: { icon: any; label: string; value?: number; sub?: string }) {
  const v = typeof value === "number" ? value : null;
  const color = v == null ? "#cbd5e1" : v >= 90 ? "#e11d48" : v >= 75 ? "#d97706" : "#059669";
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-2.5">
      <p className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500"><Icon className="h-3 w-3" />{label}</p>
      <p className="mt-0.5 font-display text-lg font-bold text-slate-900">{v == null ? "—" : `${v.toFixed(0)}%`}</p>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-200"><motion.div className="h-full rounded-full" style={{ background: color }} initial={{ width: 0 }} animate={{ width: `${v ?? 0}%` }} /></div>
      {sub && <p className="mt-1 truncate text-[10px] text-slate-500">{sub}</p>}
    </div>
  );
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button size="sm" variant="ghost" onClick={async () => { try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); } catch { /* clipboard unavailable */ } }}>
      {done ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />} {done ? "Copied" : label}
    </Button>
  );
}

function AddKeyModal({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const [mode, setMode] = useState<"generate" | "paste">("generate");
  const [name, setName] = useState("");
  const [priv, setPriv] = useState("");
  const [pass, setPass] = useState("");
  const [created, setCreated] = useState<SSHKey | null>(null);
  const [err, setErr] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const close = () => { setCreated(null); setPriv(""); setPass(""); setName(""); setErr(null); onClose(); };
  const save = async () => {
    setBusy(true); setErr(null);
    try {
      const k = await api<SSHKey>("/api/ssh-keys", { method: "POST", json: { name: name || (mode === "generate" ? "SiteForge deploy key" : "My key"), generate: mode === "generate", private_key: priv || null, passphrase: pass || null } });
      setPriv(""); setPass(""); setCreated(k); onDone();
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={close} title={created ? "SSH key added" : "Add SSH key"}>
      {created ? (
        <div className="space-y-3">
          <p className="text-sm text-slate-600">Add this public key to every server this key should manage, in <code className="rounded bg-slate-100 px-1">~/.ssh/authorized_keys</code>:</p>
          <pre className="max-h-28 overflow-auto whitespace-pre-wrap break-all rounded-xl bg-slate-50 p-3 font-mono text-[11px] text-slate-800 ring-1 ring-slate-200">{created.public_key}</pre>
          <p className="text-xs text-slate-500">Or run on the server: <code className="break-all rounded bg-slate-100 px-1">echo &quot;{created.public_key}&quot; &gt;&gt; ~/.ssh/authorized_keys</code></p>
          <div className="flex justify-end gap-2"><CopyButton text={created.public_key} label="Copy public key" /><Button onClick={close}>Done</Button></div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex gap-1 rounded-xl border border-slate-200 bg-slate-50 p-1" role="radiogroup" aria-label="Key source">
            {([["generate", "Generate a new key"], ["paste", "Use my existing key"]] as const).map(([k, l]) => (
              <button key={k} role="radio" aria-checked={mode === k} onClick={() => setMode(k)} className={clsx("flex-1 rounded-lg px-3 py-2 text-xs font-medium", mode === k ? "bg-white text-violet-700 shadow-sm" : "text-slate-500")}>{l}</button>
            ))}
          </div>
          <div><label className="label" htmlFor="kn">Name</label><input id="kn" className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder={mode === "generate" ? "SiteForge deploy key" : "My laptop key"} /></div>
          {mode === "paste" ? (
            <>
              <div><label className="label" htmlFor="kp">Private key</label>
                <textarea id="kp" rows={6} className="input font-mono text-[11px]" value={priv} onChange={(e) => setPriv(e.target.value)} placeholder={"-----BEGIN OPENSSH PRIVATE KEY-----\n…\n-----END OPENSSH PRIVATE KEY-----"} autoComplete="off" spellCheck={false} /></div>
              <div><label className="label" htmlFor="kpp">Passphrase (if the key has one)</label><input id="kpp" type="password" className="input" value={pass} onChange={(e) => setPass(e.target.value)} autoComplete="off" /></div>
            </>
          ) : <p className="rounded-xl bg-slate-50 p-3 text-xs text-slate-600 ring-1 ring-slate-200">A new ed25519 key pair is created and stored encrypted. You'll get the public key to add to your servers.</p>}
          <ErrorBox error={err} />
          <div className="flex justify-end gap-2"><Button variant="ghost" onClick={close}>Cancel</Button><Button onClick={save} loading={busy} disabled={mode === "paste" && !priv.trim()}>{mode === "generate" ? "Generate key" : "Save key"}</Button></div>
        </div>
      )}
    </Modal>
  );
}

function AddServerModal({ open, onClose, keys, sandbox, onDone }: { open: boolean; onClose: () => void; keys: SSHKey[]; sandbox: boolean; onDone: () => void }) {
  const [f, setF] = useState({ name: "", provider: "hetzner", host: "", port: 22, username: "root", ssh_key_id: "", max_sites: "", simulated: false });
  const [err, setErr] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open && !f.ssh_key_id && keys[0]) setF((x) => ({ ...x, ssh_key_id: keys[0].id })); }, [open, keys, f.ssh_key_id]);
  const set = (k: string, v: any) => setF((x) => ({ ...x, [k]: v }));
  const save = async () => {
    setBusy(true); setErr(null);
    try {
      const s = await api<ServerRow>("/api/servers", { method: "POST", json: { ...f, port: Number(f.port), max_sites: f.max_sites ? Number(f.max_sites) : null, ssh_key_id: f.simulated ? null : f.ssh_key_id || null, host: f.simulated ? "127.0.0.1" : f.host } });
      if (s.status === "error") { setErr({ message: s.error ?? "Connection failed", hint: "The server was saved. Fix the issue, then use Test on its card." }); onDone(); setBusy(false); return; }
      setF({ name: "", provider: "hetzner", host: "", port: 22, username: "root", ssh_key_id: "", max_sites: "", simulated: false });
      onDone();
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const ready = f.name.trim() && (f.simulated || (f.host.trim() && f.ssh_key_id));
  return (
    <Modal open={open} onClose={onClose} title="Add server">
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div><label className="label" htmlFor="sn">Name</label><input id="sn" className="input" value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="Hetzner FSN1 #1" /></div>
          <div><label className="label" htmlFor="sp">Provider</label><select id="sp" className="input" value={f.provider} onChange={(e) => set("provider", e.target.value)}>{Object.entries(PROVIDERS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
        </div>
        {sandbox && <label className="flex items-center gap-2 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-amber-200"><input type="checkbox" checked={f.simulated} onChange={(e) => set("simulated", e.target.checked)} /> Simulated server (sandbox: no real machine needed)</label>}
        {!f.simulated && (
          <>
            <div className="grid grid-cols-[1fr_90px] gap-3">
              <div><label className="label" htmlFor="sh">IP address or hostname</label><input id="sh" className="input font-mono" value={f.host} onChange={(e) => set("host", e.target.value)} placeholder="203.0.113.10" /></div>
              <div><label className="label" htmlFor="spt">SSH port</label><input id="spt" type="number" className="input" value={f.port} onChange={(e) => set("port", e.target.value)} /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><label className="label" htmlFor="su">SSH user</label><input id="su" className="input font-mono" value={f.username} onChange={(e) => set("username", e.target.value)} /></div>
              <div><label className="label" htmlFor="sk">SSH key</label>
                <select id="sk" className="input" value={f.ssh_key_id} onChange={(e) => set("ssh_key_id", e.target.value)}>
                  {!keys.length && <option value="">Add an SSH key first</option>}
                  {keys.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}
                </select></div>
            </div>
            <p className="text-xs text-slate-500">Non-root users need passwordless sudo. Debian/Ubuntu servers are set up automatically.</p>
          </>
        )}
        <div><label className="label" htmlFor="sm">Max websites on this server (optional)</label><input id="sm" type="number" min={1} className="input" value={f.max_sites} onChange={(e) => set("max_sites", e.target.value)} placeholder="Unlimited" /></div>
        <ErrorBox error={err} />
        <div className="flex justify-end gap-2"><Button variant="ghost" onClick={onClose}>Cancel</Button><Button onClick={save} loading={busy} disabled={!ready}><Plug className="h-4 w-4" /> Connect & save</Button></div>
      </div>
    </Modal>
  );
}


function TraefikModal({ server, onClose, onSaved }: { server: ServerRow; onClose: () => void; onSaved: () => void }) {
  const cfg = server.web_config ?? {};
  const [vals, setVals] = useState<Record<TraefikKey, string>>({
    network: server.web_overrides.network ?? "", entrypoint: server.web_overrides.entrypoint ?? "",
    http_entrypoint: server.web_overrides.http_entrypoint ?? "", certresolver: server.web_overrides.certresolver ?? "",
  });
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);
  const fields: [TraefikKey, string, string[] | undefined][] = [
    ["network", "Docker network", cfg.networks], ["entrypoint", "HTTPS entrypoint", cfg.entrypoints],
    ["certresolver", "Certificate resolver", cfg.certresolvers],
  ];
  const save = async () => {
    setSaving(true); setErr("");
    try { await api(`/api/servers/${server.id}`, { method: "PATCH", body: JSON.stringify({ web_overrides: vals }) }); onSaved(); }
    catch (e: any) { setErr(e.message); } finally { setSaving(false); }
  };
  return (
    <Modal open onClose={onClose} title={`Traefik settings · ${server.name}`}>
      <p className="mb-4 text-sm text-slate-600">These were detected from the running Traefik container{cfg.container ? ` (${cfg.container})` : ""} and the labels of the apps it already routes. Leave a field empty to keep the detected value.</p>
      <div className="space-y-3">
        {fields.map(([k, label, options]) => (
          <label key={k} className="block">
            <span className="mb-1 block text-xs font-semibold text-slate-700">{label}</span>
            <input className="input font-mono" value={vals[k]} placeholder={`detected: ${(server.web_config as any)?.[k] ?? "none"}`} list={`tr-${k}`}
              onChange={(e) => setVals({ ...vals, [k]: e.target.value.trim() })} />
            {options?.length ? <datalist id={`tr-${k}`}>{options.map((o) => <option key={o} value={o} />)}</datalist> : null}
          </label>
        ))}
      </div>
      {err && <p className="mt-3 text-sm text-rose-600">{err}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={saving} onClick={save}>Save settings</Button>
      </div>
    </Modal>
  );
}
