"use client";

import { ScrollText } from "lucide-react";
import { useEffect, useState } from "react";
import { Empty, PageHeader, Spinner } from "@/components/ui";
import { api } from "@/lib/api";

export default function AuditPage() {
  const [rows, setRows] = useState<any[] | null>(null);
  const [action, setAction] = useState("");
  useEffect(() => { const t = setTimeout(() => api(`/api/audit${action ? `?action=${encodeURIComponent(action)}` : ""}`).then(setRows).catch(() => setRows([])), 250); return () => clearTimeout(t); }, [action]);
  return (
    <div>
      <PageHeader title="Audit log" subtitle="Every sign-in, configuration change, approval, deployment and deletion." actions={<input className="input w-56" placeholder="Filter by action (e.g. website.)" value={action} onChange={(e) => setAction(e.target.value)} aria-label="Filter" />} />
      {!rows ? <Spinner /> : !rows.length ? <Empty icon={ScrollText} title="No entries" /> : (
        <div className="glass overflow-x-auto p-0">
          <table className="w-full min-w-[760px] text-sm">
            <thead><tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wider text-slate-500"><th className="p-4">When</th><th>User</th><th>Action</th><th>Target</th><th>Details</th><th>IP</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.id} className="border-b border-slate-200 align-top">
                <td className="whitespace-nowrap p-4 text-xs text-slate-500">{new Date(r.created_at).toLocaleString()}</td>
                <td className="text-xs">{r.user_email}</td>
                <td><span className="rounded-md bg-slate-100 px-2 py-0.5 font-mono text-[11px] text-cyan-700">{r.action}</span></td>
                <td className="font-mono text-[11px] text-slate-500">{r.target_type ? `${r.target_type}:${r.target_id?.slice(0, 8)}` : "—"}</td>
                <td className="max-w-md truncate pr-4 font-mono text-[11px] text-slate-500">{JSON.stringify(r.details)}</td>
                <td className="pr-4 text-xs text-slate-500">{r.ip}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
