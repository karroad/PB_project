"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, getToken, setToken } from "./api";
import type { User } from "./types";

interface AuthCtx { user: User | null; loading: boolean; login: (email: string, password: string) => Promise<void>; logout: () => void; can: (role: User["role"]) => boolean }
const Ctx = createContext<AuthCtx>(null as unknown as AuthCtx);
const RANK = { viewer: 0, operator: 1, admin: 2 };

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) { setLoading(false); return; }
    api<User>("/api/auth/me").then(setUser).catch(() => setToken(null)).finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const r = await api<{ access_token: string; user: User }>("/api/auth/login", { method: "POST", json: { email, password } });
    setToken(r.access_token);
    setUser(r.user);
  }, []);

  const logout = useCallback(() => { setToken(null); setUser(null); window.location.href = "/login"; }, []);
  const can = useCallback((role: User["role"]) => !!user && RANK[user.role] >= RANK[role], [user]);

  return <Ctx.Provider value={{ user, loading, login, logout, can }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
