"use client";

import { Plus, Users } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useToast } from "@/components/toast";
import { Button, Empty, ErrorBox, Modal, PageHeader, Spinner } from "@/components/ui";
import { api, timeAgo } from "@/lib/api";
import type { User } from "@/lib/types";

export default function UsersPage() {
  const toast = useToast();
  const [rows, setRows] = useState<User[] | null>(null);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ email: "", name: "", password: "", role: "operator" });
  const [err, setErr] = useState<any>(null);
  const load = useCallback(() => api<User[]>("/api/users").then(setRows).catch((e) => { setRows([]); setErr(e); }), []);
  useEffect(() => { load(); }, [load]);

  const update = async (u: User, patch: Partial<User>) => {
    try { await api(`/api/users/${u.id}`, { method: "PATCH", json: patch }); toast({ title: "User updated", level: "success" }); load(); }
    catch (e: any) { toast({ title: "Update failed", message: e.message, level: "error" }); }
  };
  const create = async () => {
    setErr(null);
    try { await api("/api/users", { method: "POST", json: f }); setOpen(false); setF({ email: "", name: "", password: "", role: "operator" }); load(); } catch (e) { setErr(e); }
  };

  return (
    <div>
      <PageHeader title="Users & roles" subtitle="Admins manage everything · operators create and run websites · viewers have read-only access." actions={<Button onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Invite user</Button>} />
      {!rows ? <Spinner /> : !rows.length ? <Empty icon={Users} title="No users" /> : (
        <div className="glass overflow-x-auto p-0">
          <table className="w-full min-w-[640px] text-sm">
            <thead><tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wider text-slate-500"><th className="p-4">User</th><th>Role</th><th>Status</th><th>Created</th></tr></thead>
            <tbody>{rows.map((u) => (
              <tr key={u.id} className="border-b border-slate-200">
                <td className="p-4"><p className="font-medium text-slate-900">{u.name || "—"}</p><p className="text-xs text-slate-500">{u.email}</p></td>
                <td><select className="input w-36 py-1.5" value={u.role} onChange={(e) => update(u, { role: e.target.value as User["role"] })} aria-label="Role">{["admin", "operator", "viewer"].map((r) => <option key={r}>{r}</option>)}</select></td>
                <td><button onClick={() => update(u, { is_active: !u.is_active })} className={`chip ${u.is_active ? "text-emerald-700" : "text-slate-500"}`}>{u.is_active ? "Active" : "Disabled"}</button></td>
                <td className="text-xs text-slate-500">{timeAgo(u.created_at)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      <Modal open={open} onClose={() => setOpen(false)} title="Invite user">
        <div className="space-y-3">
          <input className="input" placeholder="Email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} aria-label="Email" />
          <input className="input" placeholder="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} aria-label="Name" />
          <input className="input" type="password" placeholder="Temporary password (min 8)" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} aria-label="Password" />
          <select className="input" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} aria-label="Role">{["operator", "viewer", "admin"].map((r) => <option key={r}>{r}</option>)}</select>
          <ErrorBox error={err} />
          <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button onClick={create}>Create user</Button></div>
        </div>
      </Modal>
    </div>
  );
}
