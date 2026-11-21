"use client";

import { motion } from "framer-motion";
import { ArrowRight, Globe2, Rocket, ShieldCheck, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, ErrorBox } from "@/components/ui";
import { useAuth } from "@/lib/auth";

const FEATURES = [
  { icon: Rocket, text: "Instruction → live website, fully automated" },
  { icon: ShieldCheck, text: "Approval gates, quality gate & auto-rollback" },
  { icon: Globe2, text: "Multi-stack, multi-host, multi-registrar" },
];

export default function LoginPage() {
  const { login, user } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("admin@siteforge.local");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string } | null>(null);

  // Single redirect path: once a user exists (already signed in, or just signed in) go to the dashboard.
  useEffect(() => { if (user) router.replace("/"); }, [user, router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try { await login(email, password); } catch (err: any) { setError(err); setBusy(false); }
  };

  return (
    <div className="relative grid min-h-screen overflow-hidden lg:grid-cols-2">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -left-20 top-10 h-[500px] w-[500px] animate-aurora rounded-full bg-violet-600/30 blur-[130px]" />
        <div className="absolute bottom-0 right-0 h-[500px] w-[500px] animate-aurora rounded-full bg-cyan-500/20 blur-[130px] [animation-delay:-7s]" />
        <div className="grid-bg absolute inset-0" />
      </div>
      <div className="relative hidden flex-col justify-between p-12 lg:flex">
        <div className="flex items-center gap-3"><div className="grid h-11 w-11 place-items-center rounded-xl bg-grad"><Sparkles className="h-5 w-5" /></div><span className="font-display text-xl font-bold">SiteForge AI</span></div>
        <div>
          <motion.h1 initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="font-display text-6xl font-bold leading-[1.05] tracking-tight">
            One platform.<br /><span className="text-grad">200 autonomous</span><br />websites.
          </motion.h1>
          <p className="mt-6 max-w-md text-lg text-slate-500">Describe a website in one sentence. Eleven specialised AI agents plan, design, build, test, deploy and monitor it.</p>
          <div className="mt-10 grid max-w-md gap-3">
            {FEATURES.map(({ icon: I, text }, i) => (
              <motion.div key={text} initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.2 + i * 0.12 }} className="flex items-center gap-3 text-slate-600">
                <I className="h-5 w-5 text-cyan-700" />{text}
              </motion.div>
            ))}
          </div>
        </div>
        <p className="text-xs text-slate-500">© SiteForge AI</p>
      </div>
      <div className="relative flex items-center justify-center p-6">
        <motion.form onSubmit={submit} initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} className="glow-border glass-strong w-full max-w-md rounded-3xl bg-white/90 p-8">
          <h2 className="font-display text-2xl font-bold">Welcome back</h2>
          <p className="mb-6 mt-1 text-sm text-slate-500">Sign in to your website factory.</p>
          <div className="space-y-4">
            <div><label className="label" htmlFor="email">Email</label><input id="email" className="input" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required /></div>
            <div><label className="label" htmlFor="pw">Password</label><input id="pw" type="password" className="input" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required placeholder="Default: admin123" /></div>
            <ErrorBox error={error} />
            <Button type="submit" size="lg" loading={busy} className="w-full">Sign in <ArrowRight className="h-4 w-4" /></Button>
          </div>
        </motion.form>
      </div>
    </div>
  );
}
